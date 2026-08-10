"""把 v2 分类器跑在产品给的 A 组 30 条上——2026-08-07。

运行:uv run python _probe_v2_on_product_setA.py

数据来源:产品按《意图识别改版_产品输入需求.md》任务 1 交回的 A 组(调试用)。
B 组 30 条封存,不在这里出现,最后验收才跑。

`expect` 是**我从产品的大白话期望里映射出来的**,不是产品直接给的标签,所以每条都
附了产品原话(`why`)方便逐条核对。映射错了指出来,这里改一行就行。

映射时的两条原则:
- 产品说「先接住 / 别急着问 / 不劝」→ vent
- 产品说「肯定他 / 夸赞 / 告诉他不是」→ validate（哪怕句子本身像抱怨）
"""

import asyncio
from collections import Counter

from dotenv import load_dotenv

load_dotenv()

from app.llm.classifier_v2 import DeepSeekResponseModeClassifier  # noqa: E402

CONCURRENCY = 10

# (句子, 我映射的期望模式, 产品原话摘要)
CASES: list[tuple[str, str, str]] = [
    ("唉，恋爱谈得好累啊。", "unclear", "直接问询：怎么了，什么事情让你这么烦心"),
    ("每天上班难受死了，真不想干了。", "vent", "先接住，不劝再坚持，别立刻问为什么"),
    ("我穿点喜欢的衣服总被家长骂，我就不能有点自己喜欢的事吗", "validate", "明确告诉他可以有自己喜欢的事，别让他自我怀疑"),
    ("他总是说自己的事，谁在乎他什么样。", "vent", "接住被忽视的委屈，引导把不满讲出来"),
    ("这个app我都不常用了，你说我要不要删掉呀。", "advice", "不替他决定，帮他捋清利弊"),
    ("我把事情弄得一团糟", "vent", "先不问怎么搞砸的，先安慰，避免自我否定"),
    ("我朋友好像都不喜欢我", "vent", "不替朋友解释，正视孤独感，引导说出来"),
    ("之前的朋友都不给我朋友圈点赞了，我们是不是早就淡了", "vent", "承认单向付出难受，引导向前看"),
    ("你说他为什么跳赞我", "validate", "赞赏用户，夸品味，不让他内耗"),
    ("我总觉得他们两个更好一点", "vent", "接住孤独感，理解，再给一些建议"),
    ("他说话怎么这么凶，神经病吧", "vent", "先附和，等平静再讨论原因"),
    ("人生是只有高考这一条路吗", "advice", "不正面回答，开设更多方向，决定权交给用户"),
    ("我是不是家里的累赘啊", "validate", "肯定地告诉他“你不是”，鼓励正视优点"),
    ("我想让妈妈离婚，她总说为了我，我才不需要", "validate", "理解孝心，告诉他不需要为父母婚姻负责，夸赞善良"),
    ("人的尽头是不是只有结婚生孩子啊", "validate", "否定回答，给出人生更多可能"),
    ("羽毛球场的小帅哥我好喜欢啊，要怎么认识他啊", "advice", "一起感受悸动，陪她想怎么搭讪不尴尬"),
    ("有别人和他讲话，我受不了了", "vent", "先附和，让她感到唯一性，之后再拉回现实"),
    ("我第一次做的饼干，他会喜欢吗", "validate", "肯定用户，摆正心态和自信"),
    ("咨询也做了，心理治疗也用了，我就是迈不过去那个坎", "vent", "接住委屈，让他知道自己不是特例"),
    ("最近事情太多，我快喘不过气了", "vent", "先不急着问，先让他冷静，避免过激情绪下的风险"),
    ("姑娘明天和同学出去玩，我要不要跟着一起去啊，两个小孩子太不安全了", "advice", "理解爱女之心，开导过度紧张，劝给孩子空间"),
    ("儿子总想辍学去玩什么电竞，不同意就跟我闹，说什么阻碍了他的梦想，我要不要支持他呀", "advice", "理解焦虑，不打压也不泯灭梦想，给建议"),
    ("为什么我妈总要管这管那的，我不能有自己的人生吗", "validate", "先肯定想自由的想法，再劝说调节关系"),
    ("我还能遇到真爱吗", "validate", "肯定回复并安慰"),
    ("我总是面对一些很小的事情很纠结，好烦。。", "validate", "理解小纠结，在其他方面夸赞"),
    ("唉", "unclear", "提出问询"),
    ("活着好累啊", "vent", "先不要盲目追问，引导慢慢说出委屈；持续低迷则暂停使用"),
    ("这个世界上没有我活下来的理由了", "crisis", "走危机流程，反复确认状态，避免不可逆行为"),
    ("我到底要做到什么样", "validate", "接住委屈和愤怒，告诉他不用做什么已经很好"),
    ("在吗", "unclear", "提出问询：怎么了，有什么事情想和我分享呀"),
]


async def main() -> None:
    clf = DeepSeekResponseModeClassifier()
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(t: str) -> str:
        async with sem:
            return (await clf.classify(t)).value

    got = await asyncio.gather(*(one(c[0]) for c in CASES))

    hit = 0
    misses: list[tuple[str, str, str, str]] = []
    for (text, expect, why), pred in zip(CASES, got):
        if pred == expect:
            hit += 1
        else:
            misses.append((text, expect, pred, why))

    print(f"=== 与产品期望的一致率:{hit}/{len(CASES)} = {hit / len(CASES):.0%} ===\n")

    print("=== 产品期望分布(我的映射) ===")
    for m, n in Counter(c[1] for c in CASES).most_common():
        print(f"  {m:10s} {n:3d}  {n / len(CASES):5.0%}")
    print()

    print("=== v2 实际判定分布 ===")
    for m, n in Counter(got).most_common():
        print(f"  {m:10s} {n:3d}  {n / len(CASES):5.0%}")
    print()

    print(f"=== 不一致的 {len(misses)} 条 ===")
    for text, expect, pred, why in misses:
        print(f"  期望 {expect:9s} 实得 {pred:9s} | {text[:34]}")
        print(f"    产品原话: {why}")
    print()

    print("=== 混淆:期望(行) → 实得(列) ===")
    conf: dict[str, Counter[str]] = {}
    for (_, expect, _), pred in zip(CASES, got):
        conf.setdefault(expect, Counter())[pred] += 1
    for e in sorted(conf, key=lambda k: -sum(conf[k].values())):
        row = "  ".join(f"{k}×{v}" for k, v in conf[e].most_common())
        print(f"  {e:10s} (n={sum(conf[e].values()):2d})  {row}")


if __name__ == "__main__":
    asyncio.run(main())
