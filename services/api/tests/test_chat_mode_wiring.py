"""深聊页四个模式从 HTTP 请求一路传到 prompt 的接线测试。

ChatMode 枚举、CHAT_MODE_BLOCKS、compose_system_prompt 的 chat_mode 参数
在 2026-08-09 就写好了，但请求体一直收不到这个字段——用户在深聊页点了模式，
到不了 prompt。这组测试盯住那条链路，别再断第二次。
"""

import pytest

from app.domain.conversation.modes import ChatMode, ResponseMode
from app.domain.conversation.schemas import ChatDemoRequest
from app.llm.deepseek import _system_prompt_with_mode
from app.llm.mode_blocks import compose_system_prompt

_BASE = "【人格】你叫于你。"


# ── 请求体收得到 ────────────────────────────────────────────────────
def test_chat_mode_is_accepted_and_parsed() -> None:
    req = ChatDemoRequest(user_text="嗯", chat_mode="clarify")
    assert req.chat_mode is ChatMode.CLARIFY


def test_chat_mode_defaults_to_none() -> None:
    assert ChatDemoRequest(user_text="嗯").chat_mode is None


def test_empty_string_chat_mode_is_none_not_422() -> None:
    """前端「取消选择」传空串比传 null 省事，不能让它吃 422。"""
    assert ChatDemoRequest(user_text="嗯", chat_mode="").chat_mode is None


def test_invalid_chat_mode_is_rejected() -> None:
    with pytest.raises(ValueError):
        ChatDemoRequest(user_text="嗯", chat_mode="不存在的模式")


# ── 优先级：用户选的赢过推断的 ──────────────────────────────────────
@pytest.mark.parametrize(
    ("chat_mode", "marker"),
    [
        (ChatMode.LISTEN, "只听我说"),
        (ChatMode.CLARIFY, "帮我理清"),
        (ChatMode.REFRAME, "帮我换个角度"),
        (ChatMode.ACT, "陪我做下一步"),
    ],
)
def test_user_choice_wins_over_inference(chat_mode: ChatMode, marker: str) -> None:
    prompt = compose_system_prompt(
        _BASE, "yewne", ResponseMode.VENT, chat_mode=chat_mode
    )
    assert marker in prompt
    # 推断出的 vent 块一个字都不该出现
    assert "他只是想被听见" not in prompt


def test_inference_used_when_user_did_not_choose() -> None:
    prompt = compose_system_prompt(_BASE, "yewne", ResponseMode.VENT)
    assert "他只是想被听见" in prompt


def test_user_choice_still_applies_when_classifier_is_off() -> None:
    """分类器关掉或判失败时 mode 是 None，但用户自己选的必须照样生效。"""
    prompt = compose_system_prompt(_BASE, "yewne", None, chat_mode=ChatMode.ACT)
    assert "陪我做下一步" in prompt


def test_both_none_raises_rather_than_silently_returning_persona() -> None:
    """静默返回裸人格会让「块没生效」这种问题沉默地漏到线上。"""
    with pytest.raises(ValueError):
        compose_system_prompt(_BASE, "yewne", None)


# ── 边界约束（文档 6.1 红线）两条路径都要有 ──────────────────────────
def test_boundary_guard_present_on_both_paths() -> None:
    by_choice = compose_system_prompt(_BASE, "yewne", None, chat_mode=ChatMode.LISTEN)
    by_inference = compose_system_prompt(_BASE, "yewne", ResponseMode.VENT)
    from app.llm.mode_blocks import _BOUNDARY_GUARD

    assert _BOUNDARY_GUARD in by_choice
    assert _BOUNDARY_GUARD in by_inference


# ── provider 那一层 ────────────────────────────────────────────────
def test_deepseek_prompt_includes_user_chosen_block() -> None:
    prompt = _system_prompt_with_mode("yewne", ResponseMode.VENT, ChatMode.CLARIFY)
    assert "帮我理清" in prompt


def test_deepseek_bare_persona_only_when_both_absent() -> None:
    assert _system_prompt_with_mode("yewne", None, None) == _system_prompt_with_mode(
        "yewne", None
    )
