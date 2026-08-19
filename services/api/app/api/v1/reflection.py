"""POST /v1/reflection/reading —— 三数问心：算宫位 + 生成解释。

两段是分开的，顺序不能反：

1. `calculate_three_numbers` 是纯 Python 的确定性计算，**永远先算完**。
2. 解释由模型现写，但要过 `verify_reading_draft` 的独立校验；两次都不合格就落
   `fallback.py` 的固定文案。

模型只负责「怎么说」，宫位是「说什么」的前提，模型改不动它（§0.1）。所以即使
LLM 整个挂掉，这个接口仍然返回真实宫位 + 固定解释，而不是 5xx——这正是 §10.5
要的「不伪造结果」的另一面：结果是真的，只是解释退回到审核过的固定文案，并在
`generation_mode` 里如实标出来。

场景识别不猜：`classify_scene` 无命中或并列时返回 409 与候选列表，让用户自己选，
再带 `scene` 重新请求（§4.5「把选择权还给用户」）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.v1.deps import RedisDep, enforce_rate_limit
from app.core.config import settings
from app.domain.reflection.calculator import (
    InvalidThreeNumbersError,
    calculate_three_numbers,
)
from app.domain.reflection.generator import (
    DeepSeekReflectionGenerator,
    ReflectionExplanationGenerator,
)
from app.domain.reflection.schemas import ReflectionReading, Scene
from app.domain.reflection.service import (
    SceneNotDeterminedError,
    generate_reflection_reading,
)

router = APIRouter(prefix="/reflection", tags=["reflection"])


def get_reflection_generator() -> ReflectionExplanationGenerator:
    """依赖注入点：测试里覆盖它就能不碰网络。"""
    return DeepSeekReflectionGenerator()


GeneratorDep = Annotated[
    ReflectionExplanationGenerator, Depends(get_reflection_generator)
]


class ReadingRequest(BaseModel):
    """一次占问。三个数各自独立校验，报错要指出是第几个数。"""

    numbers: tuple[int, int, int] = Field(
        description="用户报的三个数，各自 1–99（three-number-1-99-v1）",
    )
    question: str = Field(
        min_length=1,
        max_length=500,
        description="用户写的心事原文，用于场景识别与解释生成",
    )
    scene: Scene | None = Field(
        default=None,
        description="上一次请求返回 409 后，用户从候选里选定的场景",
    )
    external_user_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="限流身份；不传则按 IP 限流",
    )


class SceneChoiceResponse(BaseModel):
    """场景无法唯一确定时返回，让前端把候选摆给用户选。"""

    detail: str = "scene_not_determined"
    candidates: tuple[Scene, ...]
    labels: dict[str, str]


@router.post(
    "/reading",
    response_model=ReflectionReading,
    responses={409: {"model": SceneChoiceResponse}},
)
async def reflection_reading(
    request: ReadingRequest,
    http_request: Request,
    redis: RedisDep,
    generator: GeneratorDep,
) -> ReflectionReading:
    await enforce_rate_limit(
        http_request,
        redis,
        bucket="reflection",
        limit=settings.rate_limit_reflection_per_minute,
        identity=request.external_user_id,
    )

    try:
        calculation = calculate_three_numbers(*request.numbers)
    except InvalidThreeNumbersError as exc:
        # 422 而不是 400：这是请求体字段不合法，和 FastAPI 自己的校验失败同类。
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        return await generate_reflection_reading(
            question=request.question,
            calculation=calculation,
            generator=generator,
            selected_scene=request.scene,
        )
    except SceneNotDeterminedError as exc:
        from app.domain.reflection.corpus import get_scene_corpus

        candidates = exc.classification.candidates or tuple(Scene)
        raise HTTPException(
            status_code=409,
            detail={
                "detail": "scene_not_determined",
                "candidates": [scene.value for scene in candidates],
                "labels": {
                    scene.value: get_scene_corpus(scene).label for scene in candidates
                },
            },
        ) from exc
