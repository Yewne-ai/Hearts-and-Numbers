"""改版前 vs 改版后,拿产品第二批的危机数据对比——2026-08-09。

运行:
    OUT=/path/to/out.md uv run python _probe_before_after.py

## 「最初的版本」指什么

线上现在跑的那条链路:
    safety.check() → 拦住就固定文案 → 放行就 v1 分类 scene → complete(persona 提示)

关键:**v1 的 scene 是死参数**（deepseek.py 的 complete() 收了但函数体里没用过），
所以"改版前"的回复只由人格 prompt 决定，和分类结果无关。v1 也**没有危机这一类**——
危机表达会被塞进 5 个 scene 之一，然后照常聊天。

所以改版前对危机的唯一防线就是 safety 层。

## 改版后

    safety.check() → 拦住就固定文案 → 放行就 v2 判 mode → complete(persona + mode 块)

危机拆成两级:crisis（明说）和 concern（情境暗示）。concern 走一个更轻的块——
不说破、顺着他的话往下接、把话头递回去。

## 这个脚本产出什么

20 条情境暗示的危机表达，每条给:v1 判成什么、v2 判成什么、safety 放不放行，
以及**两种 prompt 各生成一次回复**。回复并排放，差别看得见。
另外把 20 条"听起来像危机其实不是"的分类结果也带上，确认放宽之后没有开始误伤。
"""

import asyncio
import os
import sys
from collections import Counter
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, "_data")

from batch2 import CRISIS, NOT_CRISIS  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.domain.safety.factory import get_safety_provider  # noqa: E402
from app.llm.classifier import DeepSeekClassifier  # noqa: E402  v1
from app.llm.classifier_v2 import DeepSeekResponseModeClassifier, ResponseMode  # noqa: E402
from app.llm.deepseek import _system_prompt_for  # noqa: E402
from app.llm.mode_blocks import compose_system_prompt  # noqa: E402

PERSONA = "nini"
CONCURRENCY = 5
TEMPERATURE = 0.0
OUT = Path(os.getenv("OUT", "before_after.md"))
CAUGHT = {"crisis", "concern"}


async def ask(client: httpx.AsyncClient, system: str, text: str) -> str:
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        "temperature": TEMPERATURE,
        "top_p": 0.9,
        "frequency_penalty": 0.4,
        "presence_penalty": 0.3,
        "max_tokens": 220,
        "thinking": {"type": "disabled"},
    }
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    try:
        r = await client.post(
            f"{settings.deepseek_base_url}/chat/completions", headers=headers, json=payload
        )
        if r.status_code != 200:
            return f"[HTTP {r.status_code}]"
        return (r.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as exc:  # noqa: BLE001
        return f"[失败: {type(exc).__name__}]"


async def main() -> None:
    v1 = DeepSeekClassifier()
    v2 = DeepSeekResponseModeClassifier()
    safety, _ = get_safety_provider()
    base = _system_prompt_for(PERSONA)
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:

        async def one(text: str):
            async with sem:
                scene = (await v1.classify(text)).value
                mode = (await v2.classify(text)).value
                allowed = (await safety.check(text)).allowed
                before = await ask(client, base, text)
                after = await ask(
                    client, compose_system_prompt(base, PERSONA, ResponseMode(mode)), text
                )
                return scene, mode, allowed, before, after

        rows = await asyncio.gather(*(one(t) for t in CRISIS))

        async def cls_only(text: str):
            async with sem:
                return (await v2.classify(text)).value, (await safety.check(text)).allowed

        nc = await asyncio.gather(*(cls_only(t) for t in NOT_CRISIS))

    caught_before = sum(1 for (_, _, a, _, _) in rows if not a)
    caught_after = sum(1 for (_, m, a, _, _) in rows if m in CAUGHT or not a)
    fp_after = sum(1 for m, _ in nc if m in CAUGHT)

    print(f"危机 20 条:改版前接住 {caught_before}/20，改版后 {caught_after}/20")
    print(f"  改版后分级: {dict(Counter(m for _, m, _, _, _ in rows))}")
    print(f"  v1 把它们判成了: {dict(Counter(s for s, _, _, _, _ in rows))}")
    print(f"非危机 20 条:改版后误判 {fp_after}/20")

    lines = [
        "# 改版前 vs 改版后 · 危机表达（妮妮，temperature=0）",
        "",
        "**改版前** = 线上现状：safety 放行后，v1 判 scene（但 scene 是死参数，"
        "不影响回复），回复只由人格 prompt 决定。v1 没有危机这一类。",
        "",
        "**改版后** = v2 判 mode（危机分 crisis / concern 两级），回复 = 人格 + 对应的块。",
        "",
        f"危机 20 条：改版前两层接住 **{caught_before}/20**，改版后 **{caught_after}/20**；"
        f"非危机 20 条误判 **{fp_after}/20**。",
        "",
        "---",
        "",
    ]
    for text, (scene, mode, allowed, before, after) in zip(CRISIS, rows):
        tag = "接住" if (mode in CAUGHT or not allowed) else "**仍然漏**"
        lines += [
            f"## {text}",
            "",
            f"改版前：v1=`{scene}`　safety={'拦截' if not allowed else '放行'}　→ 当普通聊天",
            f"改版后：v2=`{mode}`　{tag}",
            "",
            f"**改版前的回复**　{before}",
            "",
            f"**改版后的回复**　{after}",
            "",
            "---",
            "",
        ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n并排文件: {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
