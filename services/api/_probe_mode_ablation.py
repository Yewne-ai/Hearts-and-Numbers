"""验证 mode 块到底改不改变回复——2026-08-07 消融对照。

运行:
    uv run python _probe_mode_ablation.py           # 生成对照文件
    OUT=/path/to/x.md uv run python _probe_mode_ablation.py

## 为什么要先做这个

`deepseek.py` 的 `complete()` 收了 `scene` 参数但**函数体里从来没用过**——系统提示只按
persona 选。也就是说分类结果目前不影响任何回复。那么在有人消费这个标签之前，
把分类准确率从 83% 提到 90% 对用户是零变化。

所以先证伪：**给了完美的 mode 标签，回复会不会朝产品期望的方向变？**
不会的话，v2 整条路就该停，不用先把管道建完。

## 设计

- 标签用产品自己的期望（`_probe_v2_on_product_setA.py` 里那份映射），**不经过分类器**。
  这样把"mode 有没有用"和"分类准不准"两个问题解耦。
- A 组 = 现状：直接复用 deepseek.py 的 `_system_prompt_for` 和全部调用参数，
  保证它就是生产行为，不是近似。
- B 组 = 人格 + 对应 mode 块（拼成一条 system message）。
- 只跑妮妮。问题是"mode 改不改变回复"，不是"mode 和人格怎么交互"，先不引入第二个变量。

产出是一份给人看的并排文件，不是分数——回复的语气和分寸得产品判，我判不了。
"""

import asyncio
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

from app.core.config import settings  # noqa: E402
from app.llm.classifier_v2 import ResponseMode  # noqa: E402
from app.llm import runtime_config  # noqa: E402
from _probe_personas import load_live_personas  # noqa: E402
from app.llm.mode_blocks import compose_system_prompt  # noqa: E402

PERSONA = os.getenv("PERSONA", "nini")
CONCURRENCY = 6
OUT = Path(os.getenv("OUT", "mode_ablation.md"))

# 温度：默认沿用 deepseek.py 里该人格的调优值（= 生产行为）。
# 设 TEMP=0 可以消掉采样噪声，让 A/B 差异只来自 mode 块——代价是人格的语气是在
# 原温度下调的，0 温度下的文风不完全等于线上。做对照时用 0，看真实观感时用默认。
_TEMP_ENV = os.getenv("TEMP")
TEMPERATURE = (
    float(_TEMP_ENV)
    if _TEMP_ENV is not None
    else runtime_config.get_params()["temperature"]
)

# LIVE=1 用快照里的线上人格（后台改过的，比默认长一倍多）；否则用本地生效的默认值。
# 2026-08-09 之前所有消融都是在默认人格上跑的，结论要以 LIVE=1 这版为准。
USE_LIVE = os.getenv("LIVE") == "1"

# (句子, 产品期望的 mode, 产品原话)
CASES: list[tuple[str, str, str]] = [
    ("唉，恋爱谈得好累啊。", "unclear", "直接问询"),
    ("每天上班难受死了，真不想干了。", "vent", "先接住，不劝再坚持，别立刻问为什么"),
    ("我穿点喜欢的衣服总被家长骂，我就不能有点自己喜欢的事吗", "validate", "明确告诉他可以有自己喜欢的事"),
    ("他总是说自己的事，谁在乎他什么样。", "vent", "接住被忽视的委屈"),
    ("这个app我都不常用了，你说我要不要删掉呀。", "advice", "不替他决定，帮他捋清利弊"),
    ("我把事情弄得一团糟", "vent", "先不问怎么搞砸的，先安慰"),
    ("我朋友好像都不喜欢我", "vent", "不替朋友解释，正视孤独感"),
    ("之前的朋友都不给我朋友圈点赞了，我们是不是早就淡了", "vent", "承认单向付出难受"),
    ("你说他为什么跳赞我", "validate", "赞赏用户，夸品味，不让他内耗"),
    ("我总觉得他们两个更好一点", "vent", "接住孤独感，理解"),
    ("他说话怎么这么凶，神经病吧", "vent", "先附和，等平静再讨论原因"),
    ("人生是只有高考这一条路吗", "advice", "不正面回答，开设更多方向"),
    ("我是不是家里的累赘啊", "validate", "肯定地告诉他“你不是”"),
    ("我想让妈妈离婚，她总说为了我，我才不需要", "validate", "理解孝心，告诉他不需要负责"),
    ("人的尽头是不是只有结婚生孩子啊", "validate", "否定回答，给出更多可能"),
    ("羽毛球场的小帅哥我好喜欢啊，要怎么认识他啊", "advice", "一起感受悸动，陪她想怎么搭讪"),
    ("有别人和他讲话，我受不了了", "vent", "先附和，让她感到唯一性"),
    ("我第一次做的饼干，他会喜欢吗", "validate", "肯定用户，摆正心态和自信"),
    ("咨询也做了，心理治疗也用了，我就是迈不过去那个坎", "vent", "接住委屈，让他知道不是特例"),
    ("最近事情太多，我快喘不过气了", "vent", "先不急着问，先让他冷静"),
    ("姑娘明天和同学出去玩，我要不要跟着一起去啊，两个小孩子太不安全了", "advice", "理解爱女之心，劝给孩子空间"),
    ("儿子总想辍学去玩什么电竞，不同意就跟我闹，说什么阻碍了他的梦想，我要不要支持他呀", "advice", "理解焦虑，不打压也不泯灭梦想"),
    ("为什么我妈总要管这管那的，我不能有自己的人生吗", "validate", "先肯定想自由的想法"),
    ("我还能遇到真爱吗", "validate", "肯定回复并安慰"),
    ("我总是面对一些很小的事情很纠结，好烦。。", "validate", "理解小纠结，在其他方面夸赞"),
    ("唉", "unclear", "提出问询"),
    ("活着好累啊", "vent", "先不要盲目追问，引导慢慢说出委屈"),
    ("这个世界上没有我活下来的理由了", "crisis", "走危机流程，反复确认状态"),
    ("我到底要做到什么样", "validate", "接住委屈和愤怒，告诉他已经很好"),
    ("在吗", "unclear", "提出问询"),
]


async def ask(client: httpx.AsyncClient, system: str, user_text: str) -> str:
    """完全照搬 deepseek.py complete() 的调用参数，保证 A 组就是生产行为。"""
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
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
            f"{settings.deepseek_base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        if r.status_code != 200:
            return f"[HTTP {r.status_code}]"
        return (r.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as exc:  # noqa: BLE001 —— 探针，失败原样写进文件方便看
        return f"[失败: {type(exc).__name__}]"


async def main() -> None:
    base = load_live_personas()[PERSONA] if USE_LIVE else runtime_config.get_persona(PERSONA)
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:

        async def pair(text: str, mode: str) -> tuple[str, str]:
            async with sem:
                a = await ask(client, base, text)
                b = await ask(
                    client, compose_system_prompt(base, PERSONA, ResponseMode(mode)), text
                )
                return a, b

        results = await asyncio.gather(*(pair(t, m) for t, m, _ in CASES))

    lines = [
        f"# mode 消融对照（{PERSONA}）",
        "",
        f"**A 组** = 只有人格 prompt　**B 组** = 人格 + mode 块"
f"　（temperature={TEMPERATURE}，人格={'线上快照' if USE_LIVE else '本地默认'}）",
        "",
        "mode 用的是产品自己写的期望，不经过分类器——这里只验证"
        "「mode 块能不能改变回复」，不掺和「分类准不准」。",
        "",
        "重点看产品明说了「别做什么」的几条：2、6、7、20。",
        "如果 A 组在这些上就已经忍住了，mode 块可以少写几个。",
        "",
        "---",
        "",
    ]
    for i, ((text, mode, why), (a, b)) in enumerate(zip(CASES, results), 1):
        lines += [
            f"## {i}. {text}",
            "",
            f"**期望模式** `{mode}`　**产品原话**：{why}",
            "",
            f"**A（现状）**　{a}",
            "",
            f"**B（加 mode 块）**　{b}",
            "",
            "更贴期望的是：□ A　□ B　□ 差不多",
            "",
            "---",
            "",
        ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"已写出 {OUT}（{len(CASES)} 条 × 2 组 = {len(CASES) * 2} 次调用）")


if __name__ == "__main__":
    asyncio.run(main())
