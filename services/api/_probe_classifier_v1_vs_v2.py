"""v1 scene 分类器 vs v2 回应模式分类器，同一批句子 A/B——2026-08-05 Day 1 收尾。

运行:
    PSYDT_JSON=/path/to/PsyDTCorpus_test_single_turn_split.json \\
        uv run python _probe_classifier_v1_vs_v2.py

用固定种子（和 `_probe_scene_on_real_corpus.py` 同一个 SEED）取同一批 100 条真实首句，
两个分类器各跑一遍，看三件事：

1. **兜底桶散到哪去了**：v1 有 29% 落 loneliness，其中大量是"判不了"而非真孤独。
   v2 把判不了单独拆成 unclear 之后，这批样本会分布到哪里。
2. **两个已知的错判有没有修好**：
   - 「你好，咨询师。」v1 判 loneliness → v2 应该判 unclear
   - 「毁灭自己的冲动」v1 判 loneliness → v2 应该判 crisis
3. **unclear 的比例是否合理**：太高说明分类器变懒（什么都不判），
   太低说明"总要选一个"的偏置没被 prompt 压住，v1 的毛病原样搬了过来。

注意 unclear 同样混了"真判不了"和"调用失败"（网络/解析失败都兜底到 unclear），
所以照例劫持两个模块的 logger.warning 分别计数。
"""

import asyncio
import json
import os
import random
from collections import Counter, defaultdict

import structlog
from dotenv import load_dotenv

load_dotenv()

from app.llm import classifier as v1_mod  # noqa: E402
from app.llm import classifier_v2 as v2_mod  # noqa: E402

SAMPLE_SIZE = int(os.getenv("SAMPLE_SIZE", "100"))
CONCURRENCY = 10
SEED = 20260805  # 必须和 _probe_scene_on_real_corpus.py 一致，否则不是同一批句子

# 上午 stability probe 里的难例 + 今天实测中 v1 判错的两条，单独盯着看。
WATCHLIST: list[str] = [
    "你好，咨询师。",
    "最近我总是被一种毁灭自己的冲动所困扰，我不明白这是怎么了。",
    "在吗",
    "烦",
    "不知道怎么说，就是有点不对劲",
    "我不是压力大，是睡不着",
    "凌晨三点还醒着，一直在想白天和我妈吵的那句话",
    "和男朋友吵架了，他到现在都不理我",
    "最近事情太多了，快撑不住了",
    "我该怎么跟他开口说这件事",
    "我这样是不是太小题大做了",
]

_fail: Counter[str] = Counter()


def _wrap(mod, tag: str) -> None:
    original = mod.logger.warning

    def counting(event: str, **kw):
        _fail[f"{tag}:{event}"] += 1
        return original(event, **kw)

    mod.logger = structlog.get_logger(__name__)
    mod.logger.warning = counting


def load_first_user_turns(path: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for rec in json.load(open(path, encoding="utf-8")):
        for msg in rec.get("messages", []):
            if msg.get("role") == "user":
                text = (msg.get("content") or "").strip()
                if text:
                    out.append((rec.get("normalizedTag", "?"), text))
                break
    return out


async def main() -> None:
    path = os.getenv("PSYDT_JSON")
    if not path:
        raise SystemExit("需要设 PSYDT_JSON 指向 PsyDTCorpus 的 json")

    _wrap(v1_mod, "v1")
    _wrap(v2_mod, "v2")

    v1 = v1_mod.DeepSeekClassifier()
    v2 = v2_mod.DeepSeekResponseModeClassifier()
    sem = asyncio.Semaphore(CONCURRENCY)

    async def run_v1(t: str) -> str:
        async with sem:
            return (await v1.classify(t)).value

    async def run_v2(t: str) -> str:
        async with sem:
            return (await v2.classify(t)).value

    print("=== 盯着看的几条 ===")
    watch = await asyncio.gather(
        *(run_v1(t) for t in WATCHLIST), *(run_v2(t) for t in WATCHLIST)
    )
    n = len(WATCHLIST)
    for text, a, b in zip(WATCHLIST, watch[:n], watch[n:]):
        print(f"  v1={a:14s} v2={b:9s}  {text[:46]}")
    print()

    rows = load_first_user_turns(path)
    random.seed(SEED)
    sample = random.sample(rows, min(SAMPLE_SIZE, len(rows)))
    texts = [t for _, t in sample]

    both = await asyncio.gather(
        *(run_v1(t) for t in texts), *(run_v2(t) for t in texts)
    )
    m = len(texts)
    v1_res, v2_res = both[:m], both[m:]

    print(f"=== v2 回应模式分布（{m} 条真实首句）===")
    for mode, cnt in Counter(v2_res).most_common():
        print(f"  {mode:10s} {cnt:4d}  {cnt / m:6.1%}")
    print()

    print("=== v1 scene（行）× v2 mode（列）：兜底桶散到哪去了 ===")
    cross: dict[str, Counter[str]] = defaultdict(Counter)
    for a, b in zip(v1_res, v2_res):
        cross[a][b] += 1
    for scene in sorted(cross, key=lambda s: -sum(cross[s].values())):
        row = "  ".join(f"{k}×{v}" for k, v in cross[scene].most_common())
        print(f"  {scene:14s} (n={sum(cross[scene].values()):3d})  {row}")
    print()

    print("=== v2 判成 unclear 的样本（最多 12 条）===")
    shown = 0
    for text, b in zip(texts, v2_res):
        if b == "unclear" and shown < 12:
            print(f"  {text[:64]}")
            shown += 1
    print()

    print("=== v2 判成 crisis 的样本（全部）===")
    for text, b in zip(texts, v2_res):
        if b == "crisis":
            print(f"  {text[:64]}")
    print()

    print("=" * 62)
    if _fail:
        print(f"!! 调用失败，分布被污染: {dict(_fail)}")
    else:
        print("调用失败: 0 —— 两边的分布都是真实分类结果")


if __name__ == "__main__":
    asyncio.run(main())
