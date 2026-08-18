"""从 prompt 快照里读线上人格——2026-08-09。

## 为什么需要这个

本地没有 `runtime_overrides.json`（它由后台改写，`.gitignore` 里，不进版本库），
所以 `runtime_config.get_persona()` 在本地只会返回 `default_personas.json` 的出厂值。
而线上跑的是被后台覆盖过的版本，两者差了一倍多：

    默认   youyou  713 字    nini   960 字
    线上   youyou 2180 字    nini  2235 字

2026-08-05~08 那几轮 mode 消融全是在**默认人格**上跑的，结论不能直接搬到线上。
这个模块从纳管的只读快照 `docs/prompt-snapshots/latest.md` 里把线上那份抠出来，
让探针能对着真实人格重测。

⚠️ 快照是导出时刻的静态副本（当前这份来自 2026-08-03，后台最后更新 2026-07-24）。
后台随时可能再改，跑之前先确认快照是不是最新的。
"""

import re
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parents[2] / "docs" / "prompt-snapshots" / "latest.md"


def load_live_personas() -> dict[str, str]:
    """解析快照，返回 {persona_key: prompt}。

    快照格式是 `## 人格:<key>(N 字)` 后面跟一个 ```text 代码块。
    """
    text = SNAPSHOT.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for m in re.finditer(
        r"^## 人格[:：]\s*(\w+).*?\n+```text\n(.*?)\n```", text, re.S | re.M
    ):
        out[m.group(1)] = m.group(2).strip()
    if not out:
        raise SystemExit(f"没能从 {SNAPSHOT} 解析出人格，格式可能变了")
    return out


def snapshot_date() -> str:
    """快照头一行的导出时间，报错时带上——判断该不该重新导。"""
    m = re.search(r"^# 线上 prompt 快照 · (\S+)", SNAPSHOT.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "未知"


def persona_for(key: str) -> str:
    """取线上某个人格。**取不到就报错，不退回别的人格。**

    2026-08-11 踩过：探针写成 `live.get("yewne") or next(iter(live.values()))`，
    快照里没有 yewne（它还没进后台），于是静默拿了优优去跑，
    回复里蹦出"连妮妮都撬不开"才发现——整轮测量作废。

    静默退回在这里代价特别大：探针的全部意义就是"对着真人格测"，
    退回之后它测的是另一个人格，但结果看起来完全正常。
    """
    live = load_live_personas()
    if key not in live:
        raise SystemExit(
            f"快照里没有人格 `{key}`（有的是 {'、'.join(live)}）。\n"
            f"快照导出于 {snapshot_date()}，{SNAPSHOT}。\n"
            f"要么这个人格还没进后台，要么快照过期了——重新导一份再跑。\n"
            f"想测本地默认文案的话用 runtime_config.get_persona('{key}')，"
            f"但别把结论当成线上的。"
        )
    return live[key]


if __name__ == "__main__":
    from app.llm import runtime_config

    live = load_live_personas()
    for key, prompt in live.items():
        local = runtime_config.get_persona(key)
        same = "一致" if local.strip() == prompt.strip() else "**不同**"
        print(f"{key:8s} 快照 {len(prompt):>5} 字   本地生效 {len(local):>5} 字   {same}")
