"""会话编排：safety → llm 对话 → 拼装响应。

数据库持久化通过可选接口注入；未提供匿名用户标识时保持无状态行为。
单元测试通过 fake provider / persistence 覆盖该模块，避免真实网络调用。

降级策略：
- safety 命中危机：直接固定文案，**不**进 LLM；
- LLM 对话抛 `LLMError`（超时/网络/非 200/解析失败）：降级到 `MockProvider`，
  响应里 `degraded=True` + `is_mock=True`，便于前端弹"临时离线"提示、
  也便于演示时一眼看出上游出问题。

[2026-08-03] 移除场景分类。原先每轮第一句会额外调一次模型把消息归到 5 个 scene
之一，但 `DeepSeekProvider.complete()` 收下 scene 后从未把它拼进 prompt——只有
MockProvider 拿它变化假回复。也就是说线上每轮白花一次模型调用、白等一份延迟，
对回复内容没有任何影响。这也是"第一条回复明显比后面慢"的主因。
（拍立得的 12 场景是另一套、仍在用，见 domain/aftercare。）
"""

import asyncio
import base64
import json
from collections.abc import AsyncGenerator
from uuid import UUID, uuid4

import structlog

from app.domain.conversation.schemas import (
    ChatDemoRequest,
    ChatDemoResponse,
    HistoryMessage,
)
from app.domain.conversation.persistence import ConversationPersistence
from app.domain.reaction.service import detect_reaction
from app.core.config import settings
from app.domain.safety import SafetyReason
from app.domain.safety.provider import SafetyProvider
from app.domain.safety.care import CareAffordance, affordance_for
from app.domain.safety.rules import SafetyResult, fallback_text_for
from app.domain.conversation.modes import ResponseMode, risk_level_for
from app.llm.factory import get_response_mode_classifier
from app.domain.speech.service import _clean_for_tts
from app.llm.provider import LLMError, LLMProvider, MockProvider
from app.tts.provider import TTSError, TTSProvider

_SENTENCE_ENDS = frozenset("。？！…\n")

logger = structlog.get_logger(__name__)

# [2026-07-29] 服务端 history 字符预算。schemas 那边的 max_length=200 只挡住条数，
# 200 条 × 2000 字符仍有 40 万字符可以进模型，所以这里再按字符总量收一道——
# 这一层才是真正的成本控制，条数上限只负责挡掉明显异常的请求。
# 24000 字符对真实会话非常宽松（本产品单条通常一两百字），正常用户不会触发。
_MAX_HISTORY_CHARS = 24_000


def _build_history(messages: list[HistoryMessage]) -> list[dict] | None:
    """转成 provider 需要的格式，并按字符预算从最近往前保留。

    [2026-07-29] 原实现是 `[{...} for m in request.history]` 直接原样转发，
    中间没有任何截断或预算控制。history 由客户端提供且不可信——绕过前端直接
    发请求就能塞进任意多历史，全部计入 DeepSeek 账单，且 safety 层只检查
    user_text 不检查 history。

    截断放在服务端而不是前端：前端的限制可以被绕过，这里不行。
    丢弃从最早的消息开始，保住最近的上下文（对话连贯性影响最小）。
    """
    if not messages:
        return None

    kept: list[dict] = []
    remaining = _MAX_HISTORY_CHARS
    for message in reversed(messages):
        remaining -= len(message.content)
        if remaining < 0:
            break
        kept.append({"role": message.role, "content": message.content})
    kept.reverse()

    dropped = len(messages) - len(kept)
    if dropped:
        logger.info(
            "chat_history_truncated",
            received=len(messages),
            kept=len(kept),
            dropped=dropped,
            budget_chars=_MAX_HISTORY_CHARS,
        )
    return kept or None


async def _detect_emotion_safe(user_text: str, provider: LLMProvider) -> str:
    """调用 provider.detect_emotion，任何异常都静默返回空串。"""
    detect = getattr(provider, "detect_emotion", None)
    if detect is None:
        return ""
    try:
        return await detect(user_text)
    except Exception:
        return ""


async def _synthesize_audio(
    reply: str,
    tts_provider: TTSProvider,
    tts_is_mock: bool,
    request_id: str,
    persona: str | None = None,
) -> tuple[str, str, bool]:
    """调用 TTS，返回 (audio_base64, content_type, is_mock)。失败时静默降级返回空音频。"""
    try:
        result = await tts_provider.synthesize(_clean_for_tts(reply), persona=persona)
        audio_b64 = (
            base64.b64encode(result.audio).decode("ascii") if result.audio else ""
        )
        return audio_b64, result.content_type, tts_is_mock
    except TTSError as exc:
        logger.warning(
            "chat_demo_tts_failed",
            request_id=request_id,
            error_code=exc.code,
            error_message=str(exc),
        )
        return "", "audio/mpeg", True


async def _persist_exchange_safe(
    persistence: ConversationPersistence | None,
    request: ChatDemoRequest,
    *,
    reply: str,
    safety_flag: SafetyReason,
    emotion: str,
    request_id: str,
    is_mock: bool,
    degraded: bool,
    mode: ResponseMode | None = None,
) -> UUID | None:
    """保存一轮对话；数据库异常只记录日志，不中断用户回复。"""
    if persistence is None or request.external_user_id is None:
        return request.conversation_id

    try:
        return await persistence.save_exchange(
            external_user_id=request.external_user_id,
            conversation_id=request.conversation_id,
            persona=request.persona.value,
            user_text=request.user_text,
            reply=reply,
            safety_flag=safety_flag,
            emotion=emotion,
            request_id=request_id,
            is_mock=is_mock,
            degraded=degraded,
            mode=mode.value if mode else "",
        )
    except Exception:
        logger.exception(
            "chat_demo_persistence_failed",
            request_id=request_id,
            conversation_id=str(request.conversation_id or ""),
        )
        return request.conversation_id


async def _safety_locked(
    persistence: ConversationPersistence | None,
    request: ChatDemoRequest,
    request_id: str,
) -> bool:
    """这个会话是否已被锁在危机状态（产品文档 8.4 的"停止普通陪伴"）。

    放在判 mode **之前**：已锁的会话不该再花一次分类调用，而且无论这轮说什么
    都走同一条固定文案。

    首轮没有会话可查——这个不变量放在服务层，不依赖某个持久化实现去保证，
    顺带省掉一次数据库往返。

    没开持久化时永远返回 False：没有会话状态就锁不住，硬装作锁住了反而会骗人。
    """
    if (
        persistence is None
        or not request.external_user_id
        or request.conversation_id is None
    ):
        return False
    try:
        locked = await persistence.is_safety_locked(
            external_user_id=request.external_user_id,
            conversation_id=request.conversation_id,
        )
    except Exception as exc:  # noqa: BLE001 —— 读锁失败不能拖垮主链路
        # 放行而不是锁住：数据库抖动不该让所有人都收到危机文案。
        # 反方向的风险（漏一次锁）由这一轮的分类器兜底。
        logger.warning("safety_lock_check_failed", request_id=request_id, error=str(exc))
        return False
    if locked:
        logger.info("chat_safety_locked_session", request_id=request_id)
    return locked


async def _lock_session_after_crisis(
    persistence: ConversationPersistence | None,
    request: ChatDemoRequest,
    conversation_id: UUID | None,
    safety_flag: SafetyReason,
    request_id: str,
) -> None:
    """判出危机之后把会话锁住，让后续每一轮都走同一条路。

    必须在落库**之后**调用——首轮时会话是那一步才创建的。
    只有危机才锁：普通敏感内容命中的处置是换个话题继续，不是终止陪伴。
    """
    if (
        persistence is None
        or not request.external_user_id
        or conversation_id is None
        or safety_flag != "crisis_keyword"
    ):
        return
    try:
        await persistence.lock_for_safety(
            external_user_id=request.external_user_id,
            conversation_id=conversation_id,
            risk_level="S3",
        )
        logger.info("chat_session_locked", request_id=request_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("chat_session_lock_failed", request_id=request_id, error=str(exc))


def _care_for(
    mode: ResponseMode | None, safety_flag: SafetyReason, locked: bool
) -> CareAffordance:
    """这一轮要不要显示现实求助入口、显示到什么程度。

    S2 那一档是安静的——一旦变成弹窗或追问，就退化成了 concern 块
    特意避免的"说破"。
    """
    if locked or safety_flag == "crisis_keyword":
        return affordance_for(risk_level="S3", session_locked=True)
    return affordance_for(
        risk_level=risk_level_for(mode) if mode else "S0", session_locked=False
    )


async def _classify_mode_safe(user_text: str, request_id: str) -> ResponseMode | None:
    """判这一轮的回应模式。开关关闭、或分类出任何问题，一律返回 None。

    返回 None 时下游行为和接入前完全一致（人格 prompt 原样，不加块），
    所以这条链路不会因为分类器故障而变差——最多是没变好。
    """
    if not settings.response_mode_enabled:
        return None
    try:
        mode = await get_response_mode_classifier().classify(user_text)
    except Exception as exc:  # noqa: BLE001 —— 分类是增强，绝不能拖垮主链路
        logger.warning("mode_classify_failed", request_id=request_id, error=str(exc))
        return None
    logger.info("chat_mode_classified", request_id=request_id, mode=mode.value)
    return mode


def _crisis_as_safety_fallback() -> SafetyResult:
    """v2 判 crisis 时，复用 safety 命中危机那条路——同一份固定文案、不进 LLM。

    这是有意的：明确说出自伤意图的时候，不该让模型现场发挥。
    concern（情境暗示、没明说）则相反，走 LLM + concern 块，说些安慰的话。
    """
    return SafetyResult(
        decision="fallback",
        reason="crisis_keyword",
        fallback_text=fallback_text_for("crisis_keyword"),
    )


async def handle_chat_demo(
    request: ChatDemoRequest,
    safety_provider: SafetyProvider,
    provider: LLMProvider,
    is_mock: bool,
    tts_provider: TTSProvider | None = None,
    tts_is_mock: bool = True,
    persistence: ConversationPersistence | None = None,
) -> ChatDemoResponse:
    """处理一次 demo 对话。

    Args:
        request: 入参（user_text + history）。
        provider: 由 `factory.get_llm_provider()` 注入的对话 provider。
        is_mock: provider 是否为 MockProvider，透传到响应里便于演示。
    """
    request_id = uuid4().hex

    safety = await safety_provider.check(request.user_text)
    mode = None
    locked = False
    if safety.allowed:
        # 会话已锁 → 直接走固定文案，不再判 mode、不进 LLM。
        locked = await _safety_locked(persistence, request, request_id)
        if locked:
            safety = _crisis_as_safety_fallback()
        else:
            mode = await _classify_mode_safe(request.user_text, request_id)
            if mode is ResponseMode.CRISIS:
                logger.info("chat_mode_crisis_fallback", request_id=request_id)
                safety = _crisis_as_safety_fallback()

    if not safety.allowed:
        logger.info(
            "chat_demo_safety_fallback",
            request_id=request_id,
            reason=safety.reason,
        )
        audio_b64, audio_ct, audio_mock = ("", "audio/mpeg", True)
        if tts_provider:
            audio_b64, audio_ct, audio_mock = await _synthesize_audio(
                safety.fallback_text,
                tts_provider,
                tts_is_mock,
                request_id,
                persona=request.persona.value,
            )
        conversation_id = await _persist_exchange_safe(
            persistence,
            request,
            reply=safety.fallback_text,
            safety_flag=safety.reason,
            emotion="",
            request_id=request_id,
            is_mock=is_mock,
            degraded=False,
            mode=mode,
        )
        await _lock_session_after_crisis(
            persistence, request, conversation_id, safety.reason, request_id
        )
        return ChatDemoResponse(
            reply=safety.fallback_text,
            safety_flag=safety.reason,
            mode=mode.value if mode else "",
            care=_care_for(mode, safety.reason, locked),
            is_mock=is_mock,
            request_id=request_id,
            conversation_id=conversation_id,
            audio_base64=audio_b64,
            audio_content_type=audio_ct,
            audio_is_mock=audio_mock,
        )

    history = _build_history(request.history)

    try:
        reply, emotion = await asyncio.gather(
            provider.complete(
                user_text=request.user_text,
                history=history,
                persona=request.persona.value,
                mode=mode,
            ),
            _detect_emotion_safe(request.user_text, provider),
        )
        logger.info(
            "chat_demo_ok",
            request_id=request_id,
            persona=request.persona.value,
            is_mock=is_mock,
            reply_chars=len(reply),
            emotion=emotion,
        )
        # 反应判断需要 reply，和 TTS 并行跑，藏在合成时间里，几乎不增加等待
        reaction_task = asyncio.create_task(
            detect_reaction(reply, request.persona.value)
        )
        audio_b64, audio_ct, audio_mock = ("", "audio/mpeg", True)
        if tts_provider:
            audio_b64, audio_ct, audio_mock = await _synthesize_audio(
                reply,
                tts_provider,
                tts_is_mock,
                request_id,
                persona=request.persona.value,
            )
        reaction = await reaction_task
        conversation_id = await _persist_exchange_safe(
            persistence,
            request,
            reply=reply,
            safety_flag="ok",
            emotion=emotion,
            request_id=request_id,
            is_mock=is_mock,
            degraded=False,
            mode=mode,
        )
        return ChatDemoResponse(
            reply=reply,
            safety_flag="ok",
            mode=mode.value if mode else "",
            care=_care_for(mode, safety.reason, locked),
            is_mock=is_mock,
            request_id=request_id,
            conversation_id=conversation_id,
            audio_base64=audio_b64,
            audio_content_type=audio_ct,
            audio_is_mock=audio_mock,
            emotion=emotion,
            reaction=reaction,
        )
    except LLMError as exc:
        logger.warning(
            "chat_demo_llm_failed_degrading_to_mock",
            request_id=request_id,
            error_code=exc.code,
            upstream_status=exc.upstream_status,
        )
        mock_reply = await MockProvider().complete(
            user_text=request.user_text,
            history=history,
            persona=request.persona.value,
        )
        audio_b64, audio_ct, audio_mock = ("", "audio/mpeg", True)
        if tts_provider:
            audio_b64, audio_ct, audio_mock = await _synthesize_audio(
                mock_reply,
                tts_provider,
                tts_is_mock,
                request_id,
                persona=request.persona.value,
            )
        conversation_id = await _persist_exchange_safe(
            persistence,
            request,
            reply=mock_reply,
            safety_flag="ok",
            emotion="",
            request_id=request_id,
            is_mock=True,
            degraded=True,
            mode=mode,
        )
        return ChatDemoResponse(
            reply=mock_reply,
            safety_flag="ok",
            mode=mode.value if mode else "",
            care=_care_for(mode, safety.reason, locked),
            is_mock=True,
            request_id=request_id,
            conversation_id=conversation_id,
            degraded=True,
            audio_base64=audio_b64,
            audio_content_type=audio_ct,
            audio_is_mock=audio_mock,
        )


async def _iter_sentences(
    token_stream: AsyncGenerator[str, None],
) -> AsyncGenerator[str, None]:
    """把 token 流按句子边界切分，每完整一句 yield 一次。

    只按整句切分。曾有"第一段在逗号处抢跑切出"的首字加速,因为会把半句话
    切成两段音频、衔接处顿挫明显,2026-07-17 按产品实听反馈移除。
    """
    buf = ""
    async for token in token_stream:
        buf += token
        if buf[-1] in _SENTENCE_ENDS:
            chunk = buf.strip()
            if chunk:
                yield chunk
            buf = ""
    if buf.strip():
        yield buf.strip()


async def stream_chat_demo(
    request: ChatDemoRequest,
    safety_provider: SafetyProvider,
    provider: LLMProvider,
    tts_provider: TTSProvider | None,
    tts_is_mock: bool,
    is_mock: bool,
    persistence: ConversationPersistence | None = None,
) -> AsyncGenerator[str, None]:
    """流式版本：LLM 逐句输出，每句完成立刻 TTS，以 SSE data 行 yield。"""
    request_id = uuid4().hex

    safety = await safety_provider.check(request.user_text)
    mode = None
    locked = False
    if safety.allowed:
        # 会话已锁 → 直接走固定文案，不再判 mode、不进 LLM。
        locked = await _safety_locked(persistence, request, request_id)
        if locked:
            safety = _crisis_as_safety_fallback()
        else:
            mode = await _classify_mode_safe(request.user_text, request_id)
            if mode is ResponseMode.CRISIS:
                logger.info("chat_mode_crisis_fallback", request_id=request_id)
                safety = _crisis_as_safety_fallback()

    if not safety.allowed:
        audio_b64, audio_ct, audio_mock = ("", "audio/mpeg", True)
        if tts_provider:
            audio_b64, audio_ct, audio_mock = await _synthesize_audio(
                safety.fallback_text,
                tts_provider,
                tts_is_mock,
                request_id,
                persona=request.persona.value,
            )
        yield (
            "data: "
            + json.dumps(
                {
                    "type": "audio",
                    "index": 0,
                    "audio_base64": audio_b64,
                    "content_type": audio_ct,
                    "is_mock": audio_mock,
                }
            )
            + "\n\n"
        )
        conversation_id = await _persist_exchange_safe(
            persistence,
            request,
            reply=safety.fallback_text,
            safety_flag=safety.reason,
            emotion="",
            request_id=request_id,
            is_mock=is_mock,
            degraded=False,
            mode=mode,
        )
        await _lock_session_after_crisis(
            persistence, request, conversation_id, safety.reason, request_id
        )
        yield (
            "data: "
            + json.dumps(
                {
                    "type": "done",
                    "reply": safety.fallback_text,
                    "safety_flag": safety.reason,
                    "is_mock": False,
                    "request_id": request_id,
                    "conversation_id": str(conversation_id)
                    if conversation_id
                    else None,
                    "degraded": False,
                }
            )
            + "\n\n"
        )
        return

    history = _build_history(request.history)

    emotion_task = asyncio.create_task(
        _detect_emotion_safe(request.user_text, provider)
    )

    full_reply = ""
    sentence_idx = 0
    response_is_mock = is_mock
    degraded = False

    try:
        token_stream = provider.stream_complete(  # type: ignore[attr-defined]
            user_text=request.user_text,
            history=history,
            persona=request.persona.value,
        )
        async for sentence in _iter_sentences(token_stream):
            full_reply += sentence
            audio_b64, audio_ct, audio_mock = ("", "audio/mpeg", True)
            if tts_provider:
                audio_b64, audio_ct, audio_mock = await _synthesize_audio(
                    sentence,
                    tts_provider,
                    tts_is_mock,
                    request_id,
                    persona=request.persona.value,
                )
            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "audio",
                        "index": sentence_idx,
                        "text": sentence,
                        "audio_base64": audio_b64,
                        "content_type": audio_ct,
                        "is_mock": audio_mock,
                    }
                )
                + "\n\n"
            )
            sentence_idx += 1

    except (LLMError, AttributeError):
        # provider 不支持流式（如 Mock）：降级到一次性调用
        try:
            full_reply = await provider.complete(
                user_text=request.user_text,
                history=history,
                persona=request.persona.value,
            )
        except LLMError:
            full_reply = await MockProvider().complete(
                user_text=request.user_text,
                history=history,
                persona=request.persona.value,
            )
            response_is_mock = True
            degraded = True
        audio_b64, audio_ct, audio_mock = ("", "audio/mpeg", True)
        if tts_provider:
            audio_b64, audio_ct, audio_mock = await _synthesize_audio(
                full_reply,
                tts_provider,
                tts_is_mock,
                request_id,
                persona=request.persona.value,
            )
        yield (
            "data: "
            + json.dumps(
                {
                    "type": "audio",
                    "index": 0,
                    "text": full_reply,
                    "audio_base64": audio_b64,
                    "content_type": audio_ct,
                    "is_mock": audio_mock,
                }
            )
            + "\n\n"
        )

    emotion = await emotion_task
    conversation_id = await _persist_exchange_safe(
        persistence,
        request,
        reply=full_reply,
        safety_flag="ok",
        emotion=emotion,
        request_id=request_id,
        is_mock=response_is_mock,
        degraded=degraded,
            mode=mode,
    )
    yield (
        "data: "
        + json.dumps(
            {
                "type": "done",
                "reply": full_reply,
                "safety_flag": "ok",
                "is_mock": response_is_mock,
                "request_id": request_id,
                "conversation_id": str(conversation_id) if conversation_id else None,
                "degraded": degraded,
                "emotion": emotion,
            }
        )
        + "\n\n"
    )
