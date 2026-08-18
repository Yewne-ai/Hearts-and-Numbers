"""DeepSeekProvider 行为测试。用 respx 桩 httpx，不打真实网络。"""

import json

import httpx
import pytest
import respx

from app.core.config import settings
from app.llm.deepseek import DeepSeekProvider
from app.llm.provider import LLMError


def _build_chat_completion_payload(content: str) -> dict:
    return {
        "id": "fake-id",
        "object": "chat.completion",
        "model": settings.deepseek_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


@pytest.mark.asyncio
async def test_deepseek_complete_returns_content_on_200():
    expected = "我在这儿，慢慢说。"
    async with respx.mock(assert_all_called=True) as mock:
        route = mock.post(f"{settings.deepseek_base_url}/chat/completions").mock(
            return_value=httpx.Response(
                200, json=_build_chat_completion_payload(expected)
            )
        )

        provider = DeepSeekProvider()
        reply = await provider.complete(user_text="睡不着")

        assert reply == expected
        sent = route.calls.last.request
        assert sent.headers["Authorization"].startswith("Bearer ")
        # httpx json= 默认 ensure_ascii=True，中文会被 \u 转义；解码后再断言
        body = json.loads(sent.content)
        assert body["model"] == settings.deepseek_model
        roles = [m["role"] for m in body["messages"]]
        assert roles == ["system", "user"]
        # 用户文本未被 scene 字符串污染
        assert body["messages"][1]["content"] == "睡不着"
        # [2026-08-11] 单一人格：传什么都用 yewne，不传也是。
        assert "你叫于你" in body["messages"][0]["content"]


@pytest.mark.asyncio
async def test_deepseek_complete_raises_llm_error_on_non_200():
    async with respx.mock() as mock:
        mock.post(f"{settings.deepseek_base_url}/chat/completions").mock(
            return_value=httpx.Response(402, json={"error": "insufficient balance"})
        )

        provider = DeepSeekProvider()
        with pytest.raises(LLMError) as exc_info:
            await provider.complete(user_text="hi")
        assert exc_info.value.code == "http_status"
        assert exc_info.value.upstream_status == 402


@pytest.mark.asyncio
async def test_deepseek_complete_raises_llm_error_on_timeout():
    async with respx.mock() as mock:
        mock.post(f"{settings.deepseek_base_url}/chat/completions").mock(
            side_effect=httpx.TimeoutException("timed out")
        )

        provider = DeepSeekProvider()
        with pytest.raises(LLMError) as exc_info:
            await provider.complete(user_text="hi")
        assert exc_info.value.code == "timeout"


@pytest.mark.asyncio
async def test_deepseek_complete_raises_llm_error_on_malformed_json():
    async with respx.mock() as mock:
        mock.post(f"{settings.deepseek_base_url}/chat/completions").mock(
            return_value=httpx.Response(200, json={"unexpected": "shape"})
        )

        provider = DeepSeekProvider()
        with pytest.raises(LLMError) as exc_info:
            await provider.complete(user_text="hi")
        assert exc_info.value.code == "decode"
