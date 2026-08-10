"""第二批数据评测——2026-08-09。

运行:
    PYTHONPATH=_data uv run python _probe_batch2.py

产品直接给了分类，没给"希望于你怎么回"，所以这批**只能验分类，验不了 mode 块**。
mode 块的验证继续用第一批那 60 条（那批带期望）。

危机不按"准确率"报。两种错的代价完全不对称，必须分开看：
  漏判 = 真危机判成别的 —— 后果不可逆
  误判 = 正常倾诉判成危机 —— 用户被当病人对待，会学会不跟你说真话
准确率把这两件事平均掉了。容忍度是政策决定，得由人定，所以这里只把两个数摆出来。

同时跑 safety 层，因为它在分类之前，真实链路里它先说了算。
"""

import asyncio
import sys
from collections import Counter

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, "_data")

from batch2 import ADVICE, CRISIS, LABELED, NOT_CRISIS, UNCLEAR, VENT  # noqa: E402

from app.domain.safety.factory import get_safety_provider  # noqa: E402
from app.llm.classifier_v2 import DeepSeekResponseModeClassifier  # noqa: E402

CONCURRENCY = 8


async def main() -> None:
    clf = DeepSeekResponseModeClassifier()
    safety, _ = get_safety_provider()
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(t: str):
        async with sem:
            return (await clf.classify(t)).value, (await safety.check(t)).allowed

    rows = await asyncio.gather(*(one(t) for t, _ in LABELED))
    pred = {t: r for (t, _), r in zip(LABELED, rows)}

    # ── 危机:漏判 ──
    # crisis 和 concern 都算"接住了"——concern 走的是更轻的处理，但不会当普通聊天
    CAUGHT = {"crisis", "concern"}
    missed = [(t, pred[t][0]) for t in CRISIS if pred[t][0] not in CAUGHT]
    blocked_c = [t for t in CRISIS if not pred[t][1]]
    print("=== 危机漏判(产品标为危机，但没判出来)===")
    print(f"  分类器漏 {len(missed)}/{len(CRISIS)}   safety 层拦住 {len(blocked_c)}/{len(CRISIS)}")
    lvl = Counter(pred[t][0] for t in CRISIS if pred[t][0] in CAUGHT)
    print(f"  其中 crisis {lvl.get('crisis', 0)} / concern {lvl.get('concern', 0)}")
    caught_by_either = [t for t in CRISIS if pred[t][0] in CAUGHT or not pred[t][1]]
    print(f"  两层合计接住 {len(caught_by_either)}/{len(CRISIS)}\n")
    for t, m in missed:
        s = "拦" if not pred[t][1] else "放"
        print(f"    [v2={m:9s} safety={s}] {t}")
    print()

    # ── 危机:误判 ──
    false_pos = [t for t in NOT_CRISIS if pred[t][0] in CAUGHT]
    blocked_n = [t for t in NOT_CRISIS if not pred[t][1]]
    print("=== 危机误判(产品标为『不是危机』，却判成了危机)===")
    print(f"  分类器误判 {len(false_pos)}/{len(NOT_CRISIS)}   safety 层误拦 {len(blocked_n)}/{len(NOT_CRISIS)}")
    for t in false_pos:
        print(f"    [v2={pred[t][0]}] {t}")
    for t in blocked_n:
        print(f"    [safety 拦截] {t}")
    print()

    # ── 其余三类 ──
    print("=== 其余三类的一致率 ===")
    for name, items in (("advice", ADVICE), ("unclear", UNCLEAR), ("vent", VENT)):
        hit = sum(pred[t][0] == name for t in items)
        dist = Counter(pred[t][0] for t in items)
        print(f"  {name:8s} {hit:>2}/{len(items):<3} {hit / len(items):>5.0%}   {dict(dist)}")
    print()

    print("=== 判错的(其余三类)===")
    for name, items in (("advice", ADVICE), ("unclear", UNCLEAR), ("vent", VENT)):
        for t in items:
            if pred[t][0] != name:
                print(f"  期望 {name:8s} 实得 {pred[t][0]:9s} | {t[:44]}")


if __name__ == "__main__":
    asyncio.run(main())
