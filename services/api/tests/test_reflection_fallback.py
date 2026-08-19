"""三数问心场景识别与固定解释测试。"""

import pytest

from app.domain.reflection import (
    Scene,
    build_fixed_reading,
    calculate_three_numbers,
    classify_scene,
    get_palace_corpus,
    get_scene_corpus,
    get_transition_corpus,
)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("我们暧昧很久了，他最近不回复我", Scene.RELATIONSHIP_UNCERTAINTY),
        ("和前任分手后，我还要去挽回吗", Scene.BREAKUP_BOUNDARY),
        ("这次考试和学校申请让我压力很大", Scene.STUDY_PRESSURE),
        ("我要不要辞职换一份工作", Scene.CAREER_CHOICE),
        ("朋友和我吵架后是不是讨厌我", Scene.INTERPERSONAL_CONFLICT),
        ("我总是纠结，越来越怀疑自己", Scene.SELF_DOUBT),
    ],
)
def test_classify_scene_selects_unique_highest_score(
    question: str, expected: Scene
) -> None:
    result = classify_scene(question)

    assert result.scene is expected
    assert result.candidates == (expected,)
    assert result.scores[expected] > 0
    assert result.matched_keywords[expected]


def test_classify_scene_does_not_guess_when_no_keywords_match() -> None:
    result = classify_scene("今天外面天气不错")

    assert result.scene is None
    assert result.candidates == ()


def test_classify_scene_does_not_break_ties_by_code_order() -> None:
    result = classify_scene("朋友和我的关系让我很困惑")

    assert result.scene is None
    assert set(result.candidates) == {
        Scene.RELATIONSHIP_UNCERTAINTY,
        Scene.INTERPERSONAL_CONFLICT,
    }


def test_fixed_reading_preserves_calculation_and_transition_grounding() -> None:
    calculation = calculate_three_numbers(2, 5, 2)
    reading = build_fixed_reading(
        calculation,
        Scene.RELATIONSHIP_UNCERTAINTY,
    )

    assert reading.numbers == (2, 5, 2)
    assert reading.result == calculation.result
    assert tuple(position.name for position in reading.positions) == tuple(
        position.name for position in calculation.positions
    )
    assert tuple(position.palace for position in reading.positions) == reading.result
    assert tuple(transition.corpus_id for transition in reading.transitions) == (
        get_transition_corpus(reading.result[0], reading.result[1]).id,
        get_transition_corpus(reading.result[1], reading.result[2]).id,
    )
    assert reading.scene is Scene.RELATIONSHIP_UNCERTAINTY
    assert reading.generation_mode == "fixed-fallback"
    assert reading.generation_attempts == 0
    assert reading.fallback_reason == "fixed-generation-requested"
    assert "不是对未来的确定预测" in reading.uncertainty


def test_fixed_reading_contains_no_corpus_forbidden_claims() -> None:
    calculation = calculate_three_numbers(99, 6, 42)

    for scene in Scene:
        reading = build_fixed_reading(calculation, scene)
        text = "\n".join(
            [
                reading.summary,
                *(position.interpretation for position in reading.positions),
                reading.uncertainty,
                reading.reflection_question,
                *reading.controllable_factors,
                reading.micro_action,
            ]
        )
        forbidden_claims = {
            claim
            for palace in calculation.result
            for claim in get_palace_corpus(palace).forbidden_claims
        }
        forbidden_claims.update(get_scene_corpus(scene).forbidden_claims)
        forbidden_claims.update(
            claim
            for transition in reading.transitions
            for claim in get_transition_corpus(
                transition.from_palace, transition.to_palace
            ).forbidden_claims
        )

        assert not forbidden_claims.intersection(text)
