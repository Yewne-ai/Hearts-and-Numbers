"""LLM provider 抽象层。

所有业务代码只依赖 `LLMProvider` Protocol；具体 provider（DeepSeek、Mock 等）
在 `app/llm/factory.py` 里按运行时配置选出。

`MockProvider` 用于本地开发与下周五 demo 兜底：未配置 key、ENV=dev 时默认走它，
保证服务在没有外部依赖时也能跑通整条链路（safety → llm → response）。

`LLMError` 是 provider 层向编排层抛出的统一错误信号。provider 自己不要直接
"降级到 mock"，那是 `domain/conversation/service.py` 的职责（保持单一职责与
可测试性）。
"""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # 避免 provider 反向依赖 classifier_v2 造成循环导入
    from app.domain.conversation.modes import ResponseMode


class LLMError(RuntimeError):
    """LLM provider 调用失败时统一抛出，便于上层决定是否降级。

    Attributes:
        code: 机器可读错误码（如 "timeout" / "http_status" / "decode" / "unknown"），
            进日志便于事后分析；不向最终用户暴露。
        upstream_status: 若来自非 200 响应，记录原始 HTTP 状态码；否则 None。
    """

    def __init__(
        self, code: str, message: str, upstream_status: int | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.upstream_status = upstream_status


class LLMProvider(Protocol):
    """LLM provider 接口。所有 provider 必须实现该签名。"""

    async def complete(
        self,
        user_text: str,
        history: list[dict] | None = None,
        persona: str = "nini",
        mode: "ResponseMode | None" = None,
    ) -> str: ...


class MockProvider:
    """固定回复的 mock provider，用于 demo 与离线开发。

    [2026-08-03] 原先按 scene 分五套模板，随场景分类一起移除。
    """

    _DEFAULT_TEMPLATE = "我在听。{echo}你愿意多说一点吗？"

    async def complete(
        self,
        user_text: str,
        history: list[dict] | None = None,
        persona: str = "nini",
        mode: "ResponseMode | None" = None,
    ) -> str:
        template = self._DEFAULT_TEMPLATE
        echo = f"你说「{user_text.strip()[:40]}」，" if user_text.strip() else ""
        return template.format(echo=echo)
