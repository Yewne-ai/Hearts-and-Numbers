"""三数问心生成、校验、重试与降级编排测试。"""

from collections.abc import Sequence

import pytest

from app.domain.reflection import (
    Palace,
    PositionName,
    ReadingDraft,
    ReadingPositionDraft,
    Scene,
    SceneNotDeterminedError,
    calculate_three_numbers,
    generate_reflection_reading,
    get_scene_corpus,
)
from app.domain.reflection.schemas import ThreeNumberResult
from app.llm.provider import LLMError


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


class FakeGenerator:
    model_version = "fake-reflection-v1"

    def __init__(self, outcomes: Sequence[ReadingDraft | LLMError]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict] = []

    async def generate(
        self,
        *,
        question: str,
        calculation: ThreeNumberResult,
        scene: Scene,
        strict: bool = False,
        validation_issues: tuple[str, ...] = (),
    ) -> ReadingDraft:
        self.calls.append(
            {
                "question": question,
                "calculation": calculation,
                "scene": scene,
                "strict": strict,
                "validation_issues": validation_issues,
            }
        )
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, LLMError):
            raise outcome
        return outcome


@pytest.mark.asyncio
async def test_service_returns_first_valid_generation() -> None:
    generator = FakeGenerator([_valid_draft()])

    reading = await generate_reflection_reading(
        question="他最近为什么不回复我",
        calculation=calculate_three_numbers(2, 5, 2),
        generator=generator,
    )

    assert reading.generation_mode == "llm"
    assert reading.generation_attempts == 1
    assert reading.generator_model_version == generator.model_version
    assert reading.fallback_reason is None
    assert len(generator.calls) == 1
    assert generator.calls[0]["strict"] is False


@pytest.mark.asyncio
async def test_service_retries_strictly_after_validation_failure() -> None:
    valid = _valid_draft()
    invalid_first = valid.positions[0].model_copy(update={"palace": Palace.SU_XI})
    invalid = valid.model_copy(
        update={"positions": (invalid_first, valid.positions[1], valid.positions[2])}
    )
    generator = FakeGenerator([invalid, valid])

    reading = await generate_reflection_reading(
        question="他最近为什么不回复我",
        calculation=calculate_three_numbers(2, 5, 2),
        generator=generator,
    )

    assert reading.generation_mode == "llm"
    assert reading.generation_attempts == 2
    assert [call["strict"] for call in generator.calls] == [False, True]
    assert generator.calls[1]["validation_issues"] == ("calculation_mismatch",)


@pytest.mark.asyncio
async def test_service_falls_back_after_two_invalid_generations() -> None:
    valid = _valid_draft()
    invalid = valid.model_copy(update={"uncertainty": "这里给出最终答案。"})
    generator = FakeGenerator([invalid, invalid])

    reading = await generate_reflection_reading(
        question="他最近为什么不回复我",
        calculation=calculate_three_numbers(2, 5, 2),
        generator=generator,
    )

    assert reading.generation_mode == "fixed-fallback"
    assert reading.generation_attempts == 2
    assert reading.generator_model_version is None
    assert reading.fallback_reason == "validation-uncertainty_missing"


@pytest.mark.asyncio
async def test_service_falls_back_after_two_generator_errors() -> None:
    generator = FakeGenerator(
        [
            LLMError("timeout", "first timeout"),
            LLMError("timeout", "second timeout"),
        ]
    )

    reading = await generate_reflection_reading(
        question="他最近为什么不回复我",
        calculation=calculate_three_numbers(2, 5, 2),
        generator=generator,
    )

    assert reading.generation_mode == "fixed-fallback"
    assert reading.fallback_reason == "generator-timeout"
    assert [call["strict"] for call in generator.calls] == [False, True]


@pytest.mark.asyncio
async def test_service_requires_user_choice_when_scene_is_not_unique() -> None:
    generator = FakeGenerator([_valid_draft()])

    with pytest.raises(SceneNotDeterminedError) as exc_info:
        await generate_reflection_reading(
            question="朋友和我的关系让我很困惑",
            calculation=calculate_three_numbers(2, 5, 2),
            generator=generator,
        )

    assert set(exc_info.value.classification.candidates) == {
        Scene.RELATIONSHIP_UNCERTAINTY,
        Scene.INTERPERSONAL_CONFLICT,
    }
    assert generator.calls == []


@pytest.mark.asyncio
async def test_selected_scene_bypasses_ambiguous_classifier() -> None:
    generator = FakeGenerator([_valid_draft()])

    reading = await generate_reflection_reading(
        question="朋友和我的关系让我很困惑",
        calculation=calculate_three_numbers(2, 5, 2),
        generator=generator,
        selected_scene=Scene.RELATIONSHIP_UNCERTAINTY,
    )

    assert reading.scene is Scene.RELATIONSHIP_UNCERTAINTY
    assert reading.generation_mode == "llm"
