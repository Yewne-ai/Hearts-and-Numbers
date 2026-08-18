"""mode 块的效果能不能盖过采样噪声——2026-08-09，3 次重复。

运行:
    REPS=3 uv run python _probe_mode_reps.py

## 为什么要重复

之前所有消融都是每格只采一次，而且用 temperature=0。两个问题：
- 单次采样分不清"块起作用了"和"这次碰巧"
- 线上跑的是 0.72，噪声比 0 温度大得多，0 温度下的结论未必迁移

所以这次用**生产温度**跑 3 遍，看 A→B 的差距是否大于遍与遍之间的波动。
如果三遍的 B 都稳定高于三遍的 A，效果就不是抽样运气。

## 只测两类

vent（不该追问）和 unclear（必须提问）——这两条能机械判定且不依赖措辞。
advice 那套关键词判据已经三次误判（跨人格、跨人格版本都失效），这里不用。
validate 从来没有可靠的机械判据，同样不测。

人格用线上快照（LIVE），不是本地默认——两者差一倍多，见 _probe_personas.py。
"""

import asyncio
import os
import statistics
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

from _probe_personas import persona_for  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.llm import runtime_config  # noqa: E402
from app.llm.classifier_v2 import ResponseMode  # noqa: E402
from app.llm.mode_blocks import compose_system_prompt  # noqa: E402

REPS = int(os.getenv("REPS", "3"))
CONCURRENCY = 8
OUT = Path(os.getenv("OUT", "mode_reps.md"))

# 取自产品第一批 A 组，只保留能机械判定的两类
VENT = [
    "每天上班难受死了，真不想干了。",
    "他总是说自己的事，谁在乎他什么样。",
    "我把事情弄得一团糟",
    "我朋友好像都不喜欢我",
    "之前的朋友都不给我朋友圈点赞了，我们是不是早就淡了",
    "我总觉得他们两个更好一点",
    "他说话怎么这么凶，神经病吧",
    "有别人和他讲话，我受不了了",
    "咨询也做了，心理治疗也用了，我就是迈不过去那个坎",
    "最近事情太多，我快喘不过气了",
    "活着好累啊",
]
UNCLEAR = ["唉，恋爱谈得好累啊。", "唉", "在吗"]


def passes(mode: str, reply: str) -> bool:
    """vent 不该以追问收场；unclear 必须以问句结尾。"""
    if mode == "vent":
        return "？" not in reply and "?" not in reply
    return reply.rstrip().endswith(("？", "?"))


async def ask(client: httpx.AsyncClient, system: str, text: str, temp: float) -> str:
    p = runtime_config.get_params()
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        "temperature": temp,
        "top_p": p["top_p"],
        "frequency_penalty": p["frequency_penalty"],
        "presence_penalty": p["presence_penalty"],
        "max_tokens": p["max_tokens"],
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
            return ""
        return (r.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception:  # noqa: BLE001
        return ""


async def main() -> None:
    temp = runtime_config.get_params()["temperature"]
    sem = asyncio.Semaphore(CONCURRENCY)
    cases = [(t, "vent") for t in VENT] + [(t, "unclear") for t in UNCLEAR]

    print(f"生产温度 {temp}，每格 {REPS} 遍，人格用线上快照")
    print(f"vent {len(VENT)} 条 + unclear {len(UNCLEAR)} 条 × 2 组 × {REPS} 遍 × 2 人格 "
          f"= {len(cases) * 2 * REPS * 2} 次调用\n")

    report: dict[str, dict[str, list[float]]] = {}

    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
        for persona in ("nini", "youyou"):
            base = persona_for(persona)
            report[persona] = {"A": [], "B": []}

            for rep in range(REPS):

                async def run(text: str, mode: str, system: str) -> bool:
                    async with sem:
                        return passes(mode, await ask(client, system, text, temp))

                a_hits, b_hits = await asyncio.gather(
                    asyncio.gather(*(run(t, m, base) for t, m in cases)),
                    asyncio.gather(
                        *(
                            run(t, m, compose_system_prompt(base, persona, ResponseMode(m)))
                            for t, m in cases
                        )
                    ),
                )
                report[persona]["A"].append(sum(a_hits) / len(cases))
                report[persona]["B"].append(sum(b_hits) / len(cases))
                print(
                    f"  {persona:7s} 第 {rep + 1} 遍   "
                    f"A {sum(a_hits):>2}/{len(cases)}   B {sum(b_hits):>2}/{len(cases)}"
                )

    print()
    print(f"{'人格':8s}{'A 三遍':>22s}{'B 三遍':>22s}{'差距':>10s}")
    print("-" * 64)
    lines = ["# mode 块 · 3 次重复（生产温度，线上人格）", ""]
    for persona, r in report.items():
        a, b = r["A"], r["B"]
        am, bm = statistics.mean(a), statistics.mean(b)
        arange = f"{min(a):.0%}~{max(a):.0%}"
        brange = f"{min(b):.0%}~{max(b):.0%}"
        print(
            f"{persona:8s}{am:>8.0%} ({arange:>9s}){bm:>10.0%} ({brange:>9s})"
            f"{bm - am:>+9.0%}"
        )
        lines.append(
            f"- **{persona}**：A {am:.0%}（{arange}）→ B {bm:.0%}（{brange}），"
            f"提升 {bm - am:+.0%}"
        )
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
