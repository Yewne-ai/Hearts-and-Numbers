"""不依赖生成模型的三数问心固定安全解释。"""

from app.domain.reflection.corpus import (
    get_palace_corpus,
    get_scene_corpus,
    get_transition_corpus,
)
from app.domain.reflection.schemas import (
    ReadingDraft,
    ReadingPositionDraft,
    ReadingTransition,
    ReflectionReading,
    Scene,
    ThreeNumberResult,
)

PROMPT_VERSION = "reflection-explanation-v1"
VERIFIER_VERSION = "reflection-verifier-v1"
UNCERTAINTY_TEXT = "这是用于自我反思的文化线索，不是对未来的确定预测。"


def _build_draft(
    calculation: ThreeNumberResult,
    scene: Scene,
) -> ReadingDraft:
    scene_entry = get_scene_corpus(scene)
    palace_entries = tuple(
        get_palace_corpus(position.palace) for position in calculation.positions
    )
    first_transition = get_transition_corpus(
        calculation.result[0], calculation.result[1]
    )
    second_transition = get_transition_corpus(
        calculation.result[1], calculation.result[2]
    )
    micro_action = scene_entry.micro_actions[0]

    return ReadingDraft(
        summary=(
            f"关于“{scene_entry.label}”，这组三数更适合帮助你整理当下。"
            f"现在可以先留意：{palace_entries[2].neutral_interpretation}。"
        ),
        positions=(
            ReadingPositionDraft(
                name=calculation.positions[0].name,
                palace=calculation.positions[0].palace,
                interpretation=(
                    f"从起势看，{palace_entries[0].neutral_interpretation}。"
                    "这可以作为理解当前触发点和情绪需要的一条线索。"
                ),
                grounding_keywords=(palace_entries[0].traditional_keywords[0],),
            ),
            ReadingPositionDraft(
                name=calculation.positions[1].name,
                palace=calculation.positions[1].palace,
                interpretation=(
                    f"从过程看，{palace_entries[1].neutral_interpretation}。"
                    f"{first_transition.allowed_interpretation}"
                ),
                grounding_keywords=(palace_entries[1].traditional_keywords[0],),
            ),
            ReadingPositionDraft(
                name=calculation.positions[2].name,
                palace=calculation.positions[2].palace,
                interpretation=(
                    f"从当下看，{palace_entries[2].neutral_interpretation}。"
                    f"{second_transition.allowed_interpretation}"
                    f"你可以先尝试：{micro_action}"
                ),
                grounding_keywords=(palace_entries[2].traditional_keywords[0],),
            ),
        ),
        uncertainty=UNCERTAINTY_TEXT,
        reflection_question=scene_entry.followup_questions[0],
        controllable_factors=(
            palace_entries[2].action_lens[0],
            scene_entry.micro_actions[0],
        ),
        micro_action=micro_action,
    )


def build_fixed_reading(
    calculation: ThreeNumberResult,
    scene: Scene,
    *,
    fallback_reason: str = "fixed-generation-requested",
    generation_attempts: int = 0,
) -> ReflectionReading:
    """组装模型不可用或校验失败时仍可展示的固定解释。"""

    draft = _build_draft(calculation, scene)
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
        generation_mode="fixed-fallback",
        prompt_version=PROMPT_VERSION,
        verifier_version=VERIFIER_VERSION,
        generation_attempts=generation_attempts,
        fallback_reason=fallback_reason,
    )
