"""把现有 scene 分类器跑在真实语料上——2026-08-05 意图分类专项 Day 1 下午。

运行:
    PSYDT_JSON=/path/to/PsyDTCorpus_test_single_turn_split.json \\
        uv run python _probe_scene_on_real_corpus.py

数据:PsyDTCorpus(华南理工 SoulChat2.0,Apache-2.0,可商用)。
    https://www.modelscope.cn/datasets/YIRONGCHEN/PsyDTCorpus
    取每段对话里 user 的第一句——那是最接近我们聊天框首句的东西。
    数据自带 normalizedTag(12 类真实咨询主题),可以当独立参照系。

要回答的三个问题(都不需要黄金标注):
    1. loneliness 占比多少?远高于"真的在说孤独"就说明兜底桶在吞东西。
       (上午的 probe 已经看到「在吗」「烦」「不知道怎么说」全落 loneliness)
    2. 我们的 5 个 scene 和 12 类主题怎么对应?一个 scene 横跨多个主题 =
       粒度太粗;多个 scene 挤在一个主题 = 切分维度不一致。
    3. 真实首句的长度分布,和我们聊天框的形态差多远。

注意:结果里的 loneliness 混了两种情况——真判成孤独,和分类失败兜底。
classify() 的设计就是任何异常都吞掉返回 loneliness(见 classifier.py),
所以这里同样劫持 logger.warning 把失败单独计出来。
"""

import asyncio
import json
import os
import random
from collections import Counter, defaultdict

import structlog
from dotenv import load_dotenv

load_dotenv()

from app.llm import classifier as classifier_mod  # noqa: E402

SAMPLE_SIZE = int(os.getenv("SAMPLE_SIZE", "100"))
CONCURRENCY = 10
SEED = 20260805  # 固定种子,换 prompt 后能跑同一批句子做对比

_failures: Counter[str] = Counter()
_original_warning = classifier_mod.logger.warning


def _counting_warning(event: str, **kw):
    _failures[event] += 1
    return _original_warning(event, **kw)


def load_first_user_turns(path: str) -> list[tuple[str, str]]:
    """返回 [(normalizedTag, 用户首句)]。"""
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

    rows = load_first_user_turns(path)
    lengths = sorted(len(t) for _, t in rows)
    print(f"语料共 {len(rows)} 条用户首句")
    print(
        f"长度分位: p10={lengths[len(lengths) // 10]}  "
        f"中位={lengths[len(lengths) // 2]}  "
        f"p90={lengths[len(lengths) * 9 // 10]}  最长={lengths[-1]}\n"
    )

    random.seed(SEED)
    sample = random.sample(rows, min(SAMPLE_SIZE, len(rows)))

    classifier_mod.logger = structlog.get_logger(__name__)
    classifier_mod.logger.warning = _counting_warning  # type: ignore[method-assign]

    clf = classifier_mod.DeepSeekClassifier()
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(text: str) -> str:
        async with sem:
            return (await clf.classify(text)).value

    scenes = await asyncio.gather(*(one(t) for _, t in sample))

    dist = Counter(scenes)
    print(f"=== 问题 1:{len(sample)} 条的 scene 分布 ===")
    for scene, n in dist.most_common():
        print(f"  {scene:14s} {n:4d}  {n / len(sample):6.1%}")
    print()

    cross: dict[str, Counter[str]] = defaultdict(Counter)
    for (tag, _), scene in zip(sample, scenes):
        cross[tag][scene] += 1
    print("=== 问题 2:真实主题(行) × 我们的 scene(列) ===")
    for tag in sorted(cross, key=lambda t: -sum(cross[t].values())):
        row = "  ".join(f"{s}×{n}" for s, n in cross[tag].most_common())
        print(f"  {tag:8s} (n={sum(cross[tag].values()):3d})  {row}")
    print()

    print("=== 问题 3:被判成 loneliness 的样本长什么样(前 12 条) ===")
    shown = 0
    for (tag, text), scene in zip(sample, scenes):
        if scene == "loneliness" and shown < 12:
            print(f"  [{tag}] {text[:70]}")
            shown += 1
    print()

    print("=" * 60)
    if _failures:
        print(f"!! 调用失败 {sum(_failures.values())} 次，已被兜底成 loneliness: {dict(_failures)}")
        print("   上面的 loneliness 占比被污染了，需要重跑")
    else:
        print("调用失败: 0 —— loneliness 占比是真实分类结果")


if __name__ == "__main__":
    asyncio.run(main())
