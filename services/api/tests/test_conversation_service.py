"""会话编排单元测试。用假 provider 覆盖各分支，不打真实网络。"""

from uuid import UUID

import pytest

from app.domain.conversation.schemas import ChatDemoRequest, HistoryMessage
from app.domain.conversation.service import (
    _MAX_HISTORY_CHARS,
    _build_history,
    handle_chat_demo,
)
from app.domain.safety import SafetyReason
from app.domain.safety.provider import LocalOnlySafetyProvider
from app.llm.provider import LLMError, LLMProvider


class _FakeOkProvider:
    async def complete(
        self,
        user_text: str,
        history: list[dict] | None = None,
        persona: str = "nini",
        mode: object | None = None,
    ) -> str:
        return f"fake-reply: {user_text}"


class _FakeFailingProvider:
    def __init__(self, code: str = "http_status", status: int | None = 402) -> None:
        self.code = code
        self.status = status

    async def complete(
        self,
        user_text: str,
        history: list[dict] | None = None,
        persona: str = "nini",
        mode: object | None = None,
    ) -> str:
        raise LLMError(self.code, "boom", upstream_status=self.status)


class _FakePersistence:
    """记录持久化参数，并返回固定会话 ID。"""

    conversation_id = UUID("00000000-0000-0000-0000-000000000123")

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def save_exchange(
        self,
        *,
        external_user_id: str,
        conversation_id: UUID | None,
        persona: str,
        user_text: str,
        reply: str,
        safety_flag: SafetyReason,
        emotion: str,
        request_id: str,
        is_mock: bool,
        degraded: bool,
        mode: str = "",
    ) -> UUID:
        self.calls.append(
            {
                "external_user_id": external_user_id,
                "conversation_id": conversation_id,
                "persona": persona,
                "user_text": user_text,
                "reply": reply,
                "safety_flag": safety_flag,
                "emotion": emotion,
                "request_id": request_id,
                "is_mock": is_mock,
                "degraded": degraded,
            }
        )
        return self.conversation_id


@pytest.mark.asyncio
async def test_handle_chat_demo_degrades_to_mock_on_llm_error():
    """对话 provider 抛 LLMError → 降级到 MockProvider，degraded=True。"""
    provider: LLMProvider = _FakeFailingProvider(code="http_status", status=402)
    safety_provider = LocalOnlySafetyProvider()
    response = await handle_chat_demo(
        ChatDemoRequest(user_text="今晚胸口闷"),
        safety_provider=safety_provider,
        provider=provider,
        is_mock=False,
    )
    assert response.degraded is True
    assert response.is_mock is True
    assert response.safety_flag == "ok"
    assert response.reply  # MockProvider 必须给出可渲染回复


@pytest.mark.asyncio
async def test_handle_chat_demo_safety_blocks_before_llm():
    """危机关键词 → 直接固定文案，**不调用 provider**。"""
    provider: LLMProvider = _FakeFailingProvider()
    safety_provider = LocalOnlySafetyProvider()
    response = await handle_chat_demo(
        ChatDemoRequest(user_text="我想自杀"),
        safety_provider=safety_provider,
        provider=provider,
        is_mock=False,
    )
    assert response.safety_flag == "crisis_keyword"
    assert response.degraded is False
    assert "诊断" not in response.reply
    assert "治疗" not in response.reply


@pytest.mark.asyncio
async def test_handle_chat_demo_persists_normal_exchange():
    """带匿名用户标识时，正常回复应保存并返回会话 ID。"""
    persistence = _FakePersistence()
    response = await handle_chat_demo(
        ChatDemoRequest(
            user_text="今天压力很大",
            external_user_id="browser-user-1",
        ),
        safety_provider=LocalOnlySafetyProvider(),
        provider=_FakeOkProvider(),
        is_mock=False,
        persistence=persistence,
    )

    assert response.conversation_id == persistence.conversation_id
    assert len(persistence.calls) == 1
    assert persistence.calls[0]["user_text"] == "今天压力很大"
    assert persistence.calls[0]["reply"] == response.reply
    assert persistence.calls[0]["safety_flag"] == "ok"


@pytest.mark.asyncio
async def test_handle_chat_demo_persists_safety_fallback():
    """Safety 拦截仍应保存用户输入和 fallback，但不调用 LLM。"""
    persistence = _FakePersistence()
    response = await handle_chat_demo(
        ChatDemoRequest(
            user_text="我想自杀",
            external_user_id="browser-user-1",
        ),
        safety_provider=LocalOnlySafetyProvider(),
        provider=_FakeFailingProvider(),
        is_mock=False,
        persistence=persistence,
    )

    assert response.conversation_id == persistence.conversation_id
    assert len(persistence.calls) == 1
    assert persistence.calls[0]["safety_flag"] == "crisis_keyword"
    assert persistence.calls[0]["reply"] == response.reply


# [2026-07-29] 以下用例覆盖新加的 history 服务端字符预算（_build_history）。
def test_build_history_returns_none_for_empty() -> None:
    """空 history 应返回 None，保持原有「不传 history 字段」的行为。"""
    assert _build_history([]) is None


def test_build_history_passes_through_normal_conversation() -> None:
    """真实会话远低于预算，必须原样透传、顺序不变。"""
    messages = [
        HistoryMessage(role="user" if i % 2 == 0 else "assistant", content=f"第{i}句")
        for i in range(20)
    ]

    result = _build_history(messages)

    assert result is not None
    assert len(result) == 20
    assert result[0]["content"] == "第0句"
    assert result[-1]["content"] == "第19句"


def test_build_history_truncates_to_char_budget_keeping_newest() -> None:
    """超预算时丢最早的、保住最近的上下文，且总字符数不超过预算。"""
    # 100 条 × 2000 字符 = 20 万字符：条数在 schemas 的 200 条上限之内，
    # 但体积远超预算——正是字符预算这一层要挡的情况。
    messages = [
        HistoryMessage(role="user", content=f"{i:04d}" + "x" * 1996) for i in range(100)
    ]

    result = _build_history(messages)

    assert result is not None
    assert len(result) < 100
    assert sum(len(m["content"]) for m in result) <= _MAX_HISTORY_CHARS
    # 保留的是尾部，所以最后一条仍是原始输入的最后一条。
    assert result[-1]["content"].startswith("0099")
