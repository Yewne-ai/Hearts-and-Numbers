"""按运行时配置选 LLM provider。

`get_llm_provider()` 返回 `(provider, is_mock)`：`is_mock` 透给上层供日志与响应字段
使用，方便前端在 demo 阶段直观看到「这条回复是不是 mock」。

"""

from app.core.config import settings
from app.domain.conversation.modes import ResponseMode  # noqa: F401
from app.llm.classifier_v2 import (
    DeepSeekResponseModeClassifier,
    MockResponseModeClassifier,
    ResponseModeClassifier,
)
from app.llm.deepseek import DeepSeekProvider
from app.llm.provider import LLMProvider, MockProvider


def _use_real_llm() -> bool:
    return settings.llm_provider == "deepseek" and bool(settings.deepseek_api_key)


def get_llm_provider() -> tuple[LLMProvider, bool]:
    if _use_real_llm():
        return DeepSeekProvider(), False
    return MockProvider(), True


def get_response_mode_classifier() -> ResponseModeClassifier:
    """回应模式分类器。无 key 时退回关键词版，保证 dev 不炸。

    调用方要自己看 `settings.response_mode_enabled`——工厂只负责给实例，
    不决定要不要用。
    """
    if _use_real_llm():
        return DeepSeekResponseModeClassifier()
    return MockResponseModeClassifier()
