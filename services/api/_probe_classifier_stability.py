"""探测 scene 分类器的稳定性——2026-08-05 意图分类专项 Day 1。

运行:uv run python _probe_classifier_stability.py

背景:`DeepSeekClassifier` 用 temperature=0.0 调用,直觉上应该每次都返回同一个 scene。
但 0 温度只是让采样取 argmax,并不保证服务端每次算出的 logits 完全一致(批处理、
路由到不同实例、浮点累加顺序都可能让结果抖)。分类结果如果本身就不稳定,那
"准确率"这个指标就没有意义——同一句话这次对下次错,再怎么调 prompt 都是白搭。
所以在做任何评测集之前,先把这件事测掉。

同时要跟"网络失败"区分开:classify() 的设计是任何异常都内部消化、返回
loneliness(见 classifier.py 的 docstring)。也就是说一次超时和一次真判成
loneliness 在返回值上完全一样。这里劫持 classifier 模块的 logger.warning
把失败次数单独记下来,否则测出来的"稳定性"可能只是在统计超时。
"""

import asyncio
from collections import Counter

import structlog
from dotenv import load_dotenv

load_dotenv()

from app.core.config import settings  # noqa: E402
from app.llm import classifier as classifier_mod  # noqa: E402

RUNS_PER_SENTENCE = 20
CONCURRENCY = 10

# 前 5 条是每个 scene 的教科书句子,后 5 条是难例(短句 / 否定 / 混合 / 模糊)。
# 难例这批更值得看——如果连典型句都不稳,问题就非常大了。
SENTENCES: list[tuple[str, str]] = [
    ("典型", "今晚又睡不着，躺了三个小时了"),
    ("典型", "那件事我反复想了好几天，绕不出来"),
    ("典型", "和男朋友吵架了，他到现在都不理我"),
    ("典型", "最近事情太多了，快撑不住了"),
    ("典型", "没什么人可以说话，就想有个人在"),
    ("难例-短", "在吗"),
    ("难例-短", "烦"),
    ("难例-否定", "我不是压力大，是睡不着"),
    ("难例-混合", "凌晨三点还醒着，一直在想白天和我妈吵的那句话"),
    ("难例-模糊", "不知道怎么说，就是有点不对劲"),
]

_failures: Counter[str] = Counter()
_original_warning = classifier_mod.logger.warning


def _counting_warning(event: str, **kw):
    """劫持 classifier 的 warning,把网络/解析失败单独计数。"""
    _failures[event] += 1
    return _original_warning(event, **kw)


async def probe() -> None:
    classifier_mod.logger = structlog.get_logger(__name__)
    classifier_mod.logger.warning = _counting_warning  # type: ignore[method-assign]

    clf = classifier_mod.DeepSeekClassifier()
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(text: str) -> str:
        async with sem:
            return (await clf.classify(text)).value

    print(f"provider={settings.llm_provider} model={settings.deepseek_model}")
    print(f"每句 {RUNS_PER_SENTENCE} 次，共 {len(SENTENCES) * RUNS_PER_SENTENCE} 次调用\n")

    unstable = 0
    for kind, text in SENTENCES:
        results = await asyncio.gather(*(one(text) for _ in range(RUNS_PER_SENTENCE)))
        dist = Counter(results)
        top, top_n = dist.most_common(1)[0]
        stable = len(dist) == 1
        unstable += 0 if stable else 1
        mark = "稳定" if stable else "!! 抖动"
        detail = "  ".join(f"{k}×{v}" for k, v in dist.most_common())
        print(f"[{mark}] {kind:8s} {text}")
        print(f"          {detail}    众数={top} ({top_n}/{RUNS_PER_SENTENCE})\n")

    print("=" * 60)
    print(f"抖动句数: {unstable}/{len(SENTENCES)}")
    if _failures:
        print(f"调用失败(会被兜底成 loneliness，污染上面结果): {dict(_failures)}")
    else:
        print("调用失败: 0 —— 上面的分布是真实的分类结果，不是超时兜底")


if __name__ == "__main__":
    asyncio.run(probe())
