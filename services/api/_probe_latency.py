"""端到端延迟——2026-08-09。

运行:
    uv run python _probe_latency.py                  # 四种组合全跑（慢，约 8 分钟）
    REPS=5 uv run python _probe_latency.py           # 加样本，n=25/组
    TTS=on uv run python _probe_latency.py           # 只跑带 TTS（= 线上配置）
    TTS=off MODE=on uv run python _probe_latency.py  # 只跑一种，最快

## 量的是什么

走真实的 `handle_chat_demo`，不是自己拼请求——所以 safety、分类、complete、
情绪识别、TTS、反应判断全都算在内，和线上同一条代码路径。

四种配置对照，把两个变量拆开：
- 开关关 / 开 —— mode 分类 + mode 块的代价
- 无 TTS / 带 TTS —— 语音合成的代价（线上是文字和音频一起返回，合成在关键路径上）

## 这个数字的边界（重要）

它**不是线上真实延迟**，缺三样：
1. 从本机发请求，不是从生产服务器（网络往返不同）
2. 单轮，没有 history。真实对话每轮都带历史，输入 token 更多
3. 没落库（PERSISTENCE_ENABLED=false）

所以拿它当**相对比较**是可靠的（同一台机器、同一批句子、只变一个开关），
拿它当绝对基线要打折——真实线上只会更慢。

句子只挑 safety 会放行的：命中安全层会直接返回固定文案，量到的是兜底路径，
不是我们想比的那条。
"""

import asyncio
import os
import statistics
import time

from dotenv import load_dotenv

load_dotenv()

from app.core.config import settings  # noqa: E402
from app.domain.conversation.schemas import ChatDemoRequest, Persona  # noqa: E402
from app.domain.conversation.service import handle_chat_demo  # noqa: E402
from app.domain.safety.factory import get_safety_provider  # noqa: E402
from app.llm.factory import get_llm_provider  # noqa: E402
from app.tts.factory import get_tts_provider  # noqa: E402

REPS = int(os.getenv("REPS", "2"))
PERSONA = Persona.NINI

# 跑哪几种组合。全跑一轮要 8 分钟左右，只想看某一个配置时用这两个变量筛。
# TTS=on 就是线上的形态——文字和音频一起返回，合成在关键路径上。
_TTS_FILTER = os.getenv("TTS", "both").lower()
_MODE_FILTER = os.getenv("MODE", "both").lower()


def _wanted(mode_enabled: bool, with_tts: bool) -> bool:
    if _TTS_FILTER != "both" and with_tts != (_TTS_FILTER == "on"):
        return False
    return _MODE_FILTER == "both" or mode_enabled == (_MODE_FILTER == "on")


# 覆盖四个模式，都是 safety 放行的
CASES = [
    "每天上班难受死了，真不想干了。",  # vent
    "我该怎么跟他开口说这件事",  # advice
    "我是不是家里的累赘啊",  # validate
    "在吗",  # unclear
    "我朋友好像都不喜欢我",  # vent
]


async def measure(mode_enabled: bool, with_tts: bool) -> tuple[list[float], list[int]]:
    settings.response_mode_enabled = mode_enabled
    provider, is_mock = get_llm_provider()
    safety, _ = get_safety_provider()
    tts, tts_is_mock = get_tts_provider() if with_tts else (None, True)

    latencies: list[float] = []
    reply_chars: list[int] = []
    for _ in range(REPS):
        for text in CASES:
            started = time.perf_counter()
            result = await handle_chat_demo(
                ChatDemoRequest(user_text=text, persona=PERSONA),
                safety_provider=safety,
                provider=provider,
                is_mock=is_mock,
                tts_provider=tts,
                tts_is_mock=tts_is_mock,
            )
            latencies.append((time.perf_counter() - started) * 1000)
            reply_chars.append(len(result.reply))
    return latencies, reply_chars


def p90(values: list[float]) -> float:
    return sorted(values)[min(len(values) - 1, int(len(values) * 0.9))]


async def main() -> None:
    original = settings.response_mode_enabled
    n = len(CASES) * REPS
    print(f"人格={PERSONA.value}  每种配置 {n} 次（{len(CASES)} 句 × {REPS} 遍）\n")
    print(f"{'配置':<18}{'中位':>9}{'均值':>9}{'p90':>9}{'回复字数':>10}")
    print("-" * 55)

    results: dict[str, float] = {}
    try:
        for label, enabled, tts in (
            ("关 · 无 TTS", False, False),
            ("开 · 无 TTS", True, False),
            ("关 · 带 TTS", False, True),
            ("开 · 带 TTS", True, True),
        ):
            if not _wanted(enabled, tts):
                continue
            lat, chars = await measure(enabled, tts)
            results[label] = statistics.median(lat)
            print(
                f"{label:<18}{statistics.median(lat):>7.0f}ms{statistics.mean(lat):>7.0f}ms"
                f"{p90(lat):>7.0f}ms{statistics.mean(chars):>9.0f}"
            )
    finally:
        settings.response_mode_enabled = original

    # 差值只在两边都跑了的时候才有意义
    def diff(a: str, b: str, label: str) -> None:
        if a in results and b in results:
            print(f"{label}：{results[a] - results[b]:+.0f}ms")

    print()
    diff("开 · 无 TTS", "关 · 无 TTS", "mode 的代价（无 TTS）")
    diff("开 · 带 TTS", "关 · 带 TTS", "mode 的代价（带 TTS）")
    diff("关 · 带 TTS", "关 · 无 TTS", "TTS 的代价（开关关）")
    if "开 · 带 TTS" in results:
        print(f"\n线上配置（开 · 带 TTS）中位：{results['开 · 带 TTS']:.0f}ms")
    print(
        "注意：本机发起、单轮无 history、未落库——真实线上只会更慢，见模块 docstring。"
    )


if __name__ == "__main__":
    asyncio.run(main())
