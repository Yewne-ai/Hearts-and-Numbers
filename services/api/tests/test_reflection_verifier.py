"""三数问心解释独立校验器测试。"""

import pytest

from app.domain.reflection import (
    Palace,
    PositionName,
    ReadingDraft,
    ReadingPositionDraft,
    Scene,
    calculate_three_numbers,
    get_scene_corpus,
    verify_reading_draft,
)


def _valid_draft() -> ReadingDraft:
    scene = get_scene_corpus(Scene.RELATIONSHIP_UNCERTAINTY)
    return ReadingDraft(
        summary="这组三数适合用来整理关系里的事实与等待边界。",
        positions=(
            ReadingPositionDraft(
                name=PositionName.ORIGIN,
                palace=Palace.LIU_LIAN,
                interpretation="起初可能有反复拉扯和未完成感。",
                grounding_keywords=("延迟",),
            ),
            ReadingPositionDraft(
                name=PositionName.PROCESS,
                palace=Palace.KONG_WANG,
                interpretation="过程中仍缺少能够确认关系走向的信息。",
                grounding_keywords=("信息不足",),
            ),
            ReadingPositionDraft(
                name=PositionName.PRESENT,
                palace=Palace.DA_AN,
                interpretation="当下更适合回到事实并照顾自己的边界。",
                grounding_keywords=("稳定",),
            ),
        ),
        uncertainty="这不是对未来的预测，只是一种自我反思线索。",
        reflection_question=scene.followup_questions[0],
        controllable_factors=("等待边界", "已经确认的事实"),
        micro_action=scene.micro_actions[0],
    )


def _issue_codes(draft: ReadingDraft) -> set[str]:
    report = verify_reading_draft(
        draft,
        calculate_three_numbers(2, 5, 2),
        Scene.RELATIONSHIP_UNCERTAINTY,
    )
    return {issue.code for issue in report.issues}


def test_verifier_accepts_grounded_draft() -> None:
    report = verify_reading_draft(
        _valid_draft(),
        calculate_three_numbers(2, 5, 2),
        Scene.RELATIONSHIP_UNCERTAINTY,
    )

    assert report.is_valid is True
    assert report.issues == ()


@pytest.mark.parametrize(
    ("changes", "expected_code"),
    [
        ({"palace": Palace.SU_XI}, "calculation_mismatch"),
        ({"grounding_keywords": ("未经授权",)}, "unsupported_grounding"),
    ],
)
def test_verifier_rejects_changed_calculation_or_unsupported_grounding(
    changes: dict,
    expected_code: str,
) -> None:
    draft = _valid_draft()
    changed_first = draft.positions[0].model_copy(update=changes)
    changed = draft.model_copy(
        update={"positions": (changed_first, draft.positions[1], draft.positions[2])}
    )

    assert expected_code in _issue_codes(changed)


def test_verifier_rejects_predictions_and_ungrounded_actions() -> None:
    draft = _valid_draft().model_copy(
        update={
            "summary": "你们注定会在一起。",
            "uncertainty": "这只是一个参考。",
            "reflection_question": "先想一想",
            "micro_action": "立刻替自己做最终决定。",
            "safety_flags": ("needs_review",),
        }
    )

    assert {
        "forbidden_claim",
        "deterministic_claim",
        "uncertainty_missing",
        "question_format",
        "ungrounded_micro_action",
        "safety_flagged",
    }.issubset(_issue_codes(draft))
