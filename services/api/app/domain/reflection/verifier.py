"""不调用模型的三数问心解释校验器。"""

from pydantic import BaseModel

from app.domain.reflection.corpus import (
    get_palace_corpus,
    get_scene_corpus,
    get_transition_corpus,
)
from app.domain.reflection.fallback import UNCERTAINTY_TEXT, VERIFIER_VERSION
from app.domain.reflection.schemas import ReadingDraft, Scene, ThreeNumberResult

_DETERMINISTIC_TERMS = ("必然", "注定", "百分百", "一定", "马上", "永远")


class ValidationIssue(BaseModel):
    """一项机器可读的致命校验问题。"""

    code: str
    message: str


class ValidationReport(BaseModel):
    """解释草稿是否满足可展示的全部硬约束。"""

    verifier_version: str = VERIFIER_VERSION
    is_valid: bool
    issues: tuple[ValidationIssue, ...]


def _all_text(draft: ReadingDraft) -> str:
    return "\n".join(
        [
            draft.summary,
            *(position.interpretation for position in draft.positions),
            draft.uncertainty,
            draft.reflection_question,
            *draft.controllable_factors,
            draft.micro_action,
        ]
    )


def verify_reading_draft(
    draft: ReadingDraft,
    calculation: ThreeNumberResult,
    scene: Scene,
) -> ValidationReport:
    """校验计算一致性、语料落地、禁止表达和现实行动。"""

    issues: list[ValidationIssue] = []
    expected_positions = calculation.positions

    for index, (actual, expected) in enumerate(
        zip(draft.positions, expected_positions, strict=True)
    ):
        if actual.name is not expected.name or actual.palace is not expected.palace:
            issues.append(
                ValidationIssue(
                    code="calculation_mismatch",
                    message=f"第 {index + 1} 段的位置或宫位与 Python 结果不一致",
                )
            )
        allowed_keywords = set(get_palace_corpus(expected.palace).traditional_keywords)
        unsupported = set(actual.grounding_keywords) - allowed_keywords
        if unsupported:
            issues.append(
                ValidationIssue(
                    code="unsupported_grounding",
                    message=(
                        f"{expected.name.value}包含未授权 grounding："
                        f"{', '.join(sorted(unsupported))}"
                    ),
                )
            )

    text = _all_text(draft)
    forbidden_claims = {
        claim
        for palace in calculation.result
        for claim in get_palace_corpus(palace).forbidden_claims
    }
    forbidden_claims.update(get_scene_corpus(scene).forbidden_claims)
    forbidden_claims.update(
        claim
        for from_palace, to_palace in zip(
            calculation.result[:-1], calculation.result[1:], strict=True
        )
        for claim in get_transition_corpus(from_palace, to_palace).forbidden_claims
    )
    for claim in sorted(forbidden_claims):
        if claim in text:
            issues.append(
                ValidationIssue(
                    code="forbidden_claim",
                    message=f"命中语料禁止表达：{claim}",
                )
            )

    for term in _DETERMINISTIC_TERMS:
        if term in text:
            issues.append(
                ValidationIssue(
                    code="deterministic_claim",
                    message=f"命中确定性表达：{term}",
                )
            )

    if "不是" not in draft.uncertainty or "预测" not in draft.uncertainty:
        issues.append(
            ValidationIssue(
                code="uncertainty_missing",
                message=f"不确定性说明必须表达“{UNCERTAINTY_TEXT}”的核心含义",
            )
        )

    scene_entry = get_scene_corpus(scene)
    if draft.micro_action not in scene_entry.micro_actions:
        issues.append(
            ValidationIssue(
                code="ungrounded_micro_action",
                message="现实小行动必须逐字选自当前场景草案",
            )
        )

    if not draft.reflection_question.rstrip().endswith(("？", "?")):
        issues.append(
            ValidationIssue(
                code="question_format",
                message="温和追问必须是一个问句",
            )
        )

    if draft.safety_flags:
        issues.append(
            ValidationIssue(
                code="safety_flagged",
                message="生成草稿返回安全标记，不能展示普通占问解释",
            )
        )

    return ValidationReport(is_valid=not issues, issues=tuple(issues))
