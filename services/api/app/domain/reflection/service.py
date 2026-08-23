"""三数问心解释编排：生成、独立校验、重试与固定降级。"""

from app.domain.reflection.corpus import (
    get_scene_corpus,
    get_transition_corpus,
)
from app.domain.reflection.fallback import (
    PROMPT_VERSION,
    VERIFIER_VERSION,
    build_fixed_reading,
)
from app.domain.reflection.generator import ReflectionExplanationGenerator
from app.domain.reflection.scene_classifier import classify_scene
from app.domain.reflection.schemas import (
    ReadingDraft,
    ReadingTransition,
    ReflectionReading,
    Scene,
    SceneClassification,
    ThreeNumberResult,
)
from app.domain.reflection.verifier import verify_reading_draft
from app.llm.provider import LLMError


class SceneNotDeterminedError(ValueError):
    """场景无命中或并列时要求调用方让用户选择。"""

    def __init__(self, classification: SceneClassification) -> None:
        super().__init__("无法唯一确定场景，请让用户从候选场景中主动选择")
        self.classification = classification


def _resolve_scene(question: str, selected_scene: Scene | None) -> Scene:
    if selected_scene is not None:
        return selected_scene
    classification = classify_scene(question)
    if classification.scene is None:
        raise SceneNotDeterminedError(classification)
    return classification.scene


def _assemble_llm_reading(
    draft: ReadingDraft,
    calculation: ThreeNumberResult,
    scene: Scene,
    generator: ReflectionExplanationGenerator,
    attempts: int,
) -> ReflectionReading:
    scene_entry = get_scene_corpus(scene)
    transitions = (
        get_transition_corpus(calculation.result[0], calculation.result[1]),
        get_transition_corpus(calculation.result[1], calculation.result[2]),
    )
    return ReflectionReading(
        **draft.model_dump(),
        numbers=calculation.numbers,
        result=calculation.result,
        scene=scene,
        scene_label=scene_entry.label,
        transitions=(
            ReadingTransition(
                corpus_id=transitions[0].id,
                from_palace=transitions[0].from_palace,
                to_palace=transitions[0].to_palace,
                interpretation=transitions[0].allowed_interpretation,
            ),
            ReadingTransition(
                corpus_id=transitions[1].id,
                from_palace=transitions[1].from_palace,
                to_palace=transitions[1].to_palace,
                interpretation=transitions[1].allowed_interpretation,
            ),
        ),
        generation_mode="llm",
        generator_model_version=generator.model_version,
        prompt_version=PROMPT_VERSION,
        verifier_version=VERIFIER_VERSION,
        generation_attempts=attempts,
    )


async def generate_reflection_reading(
    *,
    question: str,
    calculation: ThreeNumberResult,
    generator: ReflectionExplanationGenerator,
    selected_scene: Scene | None = None,
) -> ReflectionReading:
    """最多生成两次；两次均失败后返回固定 fallback。"""

    scene = _resolve_scene(question, selected_scene)
    issues: tuple[str, ...] = ()
    last_reason = "generation-not-attempted"

    for attempt in (1, 2):
        try:
            draft = await generator.generate(
                question=question,
                calculation=calculation,
                scene=scene,
                strict=attempt == 2,
                validation_issues=issues,
            )
        except LLMError as exc:
            last_reason = f"generator-{exc.code}"
            if exc.code == "configuration":
                return build_fixed_reading(
                    calculation,
                    scene,
                    fallback_reason=last_reason,
                    generation_attempts=attempt,
                )
            issues = (last_reason,)
            continue

        report = verify_reading_draft(draft, calculation, scene)
        if report.is_valid:
            return _assemble_llm_reading(
                draft,
                calculation,
                scene,
                generator,
                attempt,
            )
        issues = tuple(issue.code for issue in report.issues)
        last_reason = "validation-" + ",".join(issues)

    return build_fixed_reading(
        calculation,
        scene,
        fallback_reason=last_reason,
        generation_attempts=2,
    )
