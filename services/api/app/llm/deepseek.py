"""DeepSeek provider.

封装规则：
- 只做"按 persona 拼 prompt + history → 调 DeepSeek /chat/completions → 解析 content → 返回"。
- 任何失败（超时、网络、非 200、JSON 结构异常）统一抛 `LLMError`，由
  `domain/conversation/service.py` 决定是否降级到 Mock。
- system prompt 在这里按场景分化，符合仓库红线：
  禁医疗/诊断措辞、不使用"治疗""急救"等词；危机路径已由 `domain/safety` 拦截，
  这里只负责"陪伴/复盘"语气。
"""

import json
from collections.abc import AsyncGenerator

import httpx

from app.core.config import settings
from app.llm.provider import LLMError
from app.llm import runtime_config
from app.domain.conversation.modes import ResponseMode
from app.llm.mode_blocks import compose_system_prompt

# [2026-08-03] 人格 prompt 和采样参数都不在这个文件里了，走 runtime_config：
#   出厂默认 → app/llm/default_personas.json（defaults.py 读它）
#   线上实际 → app/llm/runtime_overrides.json（产品在 /internal 后台改，覆盖默认值）
# 这里原先有 _MOMO_/_IRIS_/_ROCKY_PERSONA 三个常量，键是改名前的 momo/iris/rocky，
# 早已不是合法 persona，_PERSONAS 字典定义后也从没被引用过——纯死代码，本次删除。
# 想改优优/妮妮说话的方式，改后台或 default_personas.json，不要在这里加常量。


def _system_prompt_for(persona: str) -> str:
    # 客户端传什么都用 yewne——见 runtime_config.resolve_persona 的说明。
    return runtime_config.get_persona(runtime_config.resolve_persona(persona))


def _system_prompt_with_mode(persona: str, mode: "ResponseMode | None") -> str:
    """人格 prompt；给了 mode 就在后面追加对应的回应方式块。

    mode 为 None（开关关闭、或分类失败）时行为和以前完全一致。
    块必须拼在人格**后面**——2026-08-09 实测模型会听更近的那条：线上人格写着
    "情绪支持 4 到 7 句"，而 vent 块要求说完一句就停，拼在后面时块赢。
    """
    base = _system_prompt_for(persona)
    if mode is None:
        return base
    return compose_system_prompt(base, persona, mode)


class DeepSeekProvider:
    async def complete(
        self,
        user_text: str,
        history: list[dict] | None = None,
        persona: str = "nini",
        mode: ResponseMode | None = None,
    ) -> str:
        messages: list[dict] = [
            {"role": "system", "content": _system_prompt_with_mode(persona, mode)}
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        _p = runtime_config.get_params()
        payload = {
            "model": _p["model"],
            "messages": messages,
            "temperature": _p["temperature"],
            "top_p": _p["top_p"],
            "frequency_penalty": _p["frequency_penalty"],
            "presence_penalty": _p["presence_penalty"],
            "max_tokens": _p["max_tokens"],
            # v4-flash 是推理模型，答案前会先吐 reasoning_content；这个人格 prompt
            # 规则已经写得很死，不需要链式推理，关掉 thinking 既省延迟也避免
            # reasoning token 把 max_tokens 挤占到把回复截断（2026-07-26 踩过，
            # 线上实测有真实回复被截断成半句话）。
            "thinking": {"type": "disabled"},
        }
        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        url = f"{settings.deepseek_base_url}/chat/completions"

        try:
            async with httpx.AsyncClient(
                timeout=settings.llm_timeout_seconds
            ) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMError("timeout", f"deepseek timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMError("network", f"deepseek network error: {exc}") from exc

        if response.status_code != 200:
            raise LLMError(
                "http_status",
                f"deepseek non-200: {response.status_code}",
                upstream_status=response.status_code,
            )

        try:
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError("decode", f"deepseek decode error: {exc}") from exc

    async def stream_complete(
        self,
        user_text: str,
        history: list[dict] | None = None,
        persona: str = "nini",
        mode: ResponseMode | None = None,
    ) -> AsyncGenerator[str, None]:
        """流式输出 token，逐个 yield。"""
        messages: list[dict] = [
            {"role": "system", "content": _system_prompt_with_mode(persona, mode)}
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        _p = runtime_config.get_params()
        payload = {
            "model": _p["model"],
            "messages": messages,
            "temperature": _p["temperature"],
            "top_p": _p["top_p"],
            "frequency_penalty": _p["frequency_penalty"],
            "presence_penalty": _p["presence_penalty"],
            "max_tokens": _p["max_tokens"],
            "stream": True,
            # 同 complete()：关掉推理，省延迟也避免截断。
            "thinking": {"type": "disabled"},
        }
        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        url = f"{settings.deepseek_base_url}/chat/completions"

        try:
            async with httpx.AsyncClient(
                timeout=settings.llm_timeout_seconds
            ) as client:
                async with client.stream(
                    "POST", url, headers=headers, json=payload
                ) as response:
                    if response.status_code != 200:
                        await response.aread()
                        raise LLMError(
                            "http_status",
                            f"deepseek stream non-200: {response.status_code}",
                            upstream_status=response.status_code,
                        )
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            token = chunk["choices"][0]["delta"].get("content", "")
                            if token:
                                yield token
                        except (KeyError, IndexError, ValueError):
                            continue
        except httpx.TimeoutException as exc:
            raise LLMError("timeout", f"deepseek stream timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMError("network", f"deepseek stream network error: {exc}") from exc

    async def detect_emotion(self, user_text: str) -> str:
        """一次轻量调用判断用户文本的主要情绪。返回单个中文词；任何失败返回空串。"""
        messages = [
            {
                "role": "system",
                "content": (
                    "你是情绪识别器。根据用户说的话，从以下标签中选出最贴切的一个，"
                    "只输出标签本身，不加任何其他内容：\n"
                    "焦虑、委屈、孤独、愤怒、失落、疲惫、迷茫、难过、开心、平静、压抑、无奈"
                ),
            },
            {"role": "user", "content": user_text},
        ]
        payload = {
            "model": settings.deepseek_model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 16,
            # v4-flash 是推理模型，默认会先吐一段 reasoning_content 再给答案；
            # 这里只要一个词，关掉 thinking 避免推理 token 把 max_tokens 提前吃完
            # 导致 content 截断成空串（2026-07-26 踩过）。
            "thinking": {"type": "disabled"},
        }
        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        url = f"{settings.deepseek_base_url}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code != 200:
                    return ""
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception:
            return ""
