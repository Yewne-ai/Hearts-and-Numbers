"""小人反应判断：据于你刚写好的这句回答，选一个该播的动画反应。

给 Unity / 网页用：让后端直接把"该演哪个动作"算好返回，前端拿到 `reaction` 直接
play 对应动画，不用自己从情绪去映射。

为什么据"回答"而不是"用户情绪"选：像"肯定 / 否定"这种，取决于于你这句到底是在
认同还是在反驳用户，光看用户情绪分不出来；而写回答的模型最清楚自己刚说的是什么。

设计要点（和拍立得 aftercare 一致）：
- **自包含**，直接 httpx 调 DeepSeek，只读 settings 已有字段，**不 import 分叉的
  deepseek.py**，部署零牵连。
- **每个人格只能选它真有动画的那几个反应**（见 `_REACTION_SETS`），否则会 play 空。
- 任何失败 / 空回答 都静默返回 ""，前端遇到空就回落 Idle。
"""

import httpx

from app.llm.runtime_config import resolve_persona
from app.core.config import settings

# 每个人格实际做了动画的反应集合（据美术给的动画表）。
_REACTION_SETS: dict[str, tuple[str, ...]] = {
    # [2026-08-11] 单一人格。取两个旧人格的并集——合并之后没有理由再砍掉
    # 任何一种反应，而且少给一种就等于用户表达不了那种感受。
    "yewne": ("开心", "伤心", "疑惑", "关心", "肯定", "否定"),
    "youyou": ("开心", "伤心", "疑惑", "肯定", "否定"),   # 优优没有"关心"
    "nini": ("开心", "伤心", "疑惑", "关心"),             # 妮妮没有"肯定/否定"
}

# 每个反应的含义，喂给模型好让它对着回答判断。
_MEANINGS: dict[str, str] = {
    "开心": "这句在轻松、逗趣、分享愉快",
    "伤心": "这句在陪着一起难过、共情低落",
    "疑惑": "这句在困惑、一起想不明白、或反问澄清",
    "肯定": "这句在【顺着】用户、认同 ta 的看法或感受，站在 ta 那边（'你说得对''你有理由这么想''确实是这样'）",
    "否定": "这句在【反驳、纠正】用户，跟 ta 唱反调、否定 ta 的消极自我判断（'不对''别瞎说''没那么糟''这不怪你'）。判断依据是这句话在跟用户【对着说】，而不是顺着说",
    "关心": "这句在关切、安慰、心疼、叮嘱照顾好自己",
}


async def detect_reaction(reply: str, persona: str) -> str:
    """据于你这句回答，从该人格可用的反应里选一个。失败/无适用则返回 ""。"""
    allowed = _REACTION_SETS.get(resolve_persona(persona))
    if not allowed or not reply.strip() or not settings.deepseek_api_key:
        return ""

    options = "\n".join(f"- {tag}：{_MEANINGS[tag]}" for tag in allowed)
    system = (
        "你在给一个虚拟陪伴角色挑一个面部/肢体反应动画。下面是这个角色刚对用户说的一句话，"
        "请判断这句话的情绪基调，从给定选项里选**最贴切的一个**，只输出那个词本身，"
        "不要标点、不要解释。\n\n可选反应：\n" + options
    )
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": reply},
        ],
        "temperature": 0.1,
        "max_tokens": 16,
        # v4-flash 是推理模型，默认会先吐一段 reasoning_content 再给答案；
        # 这里只要一个词，关掉 thinking 避免推理 token 把 max_tokens 提前吃完
        # 导致 content 截断成空串（2026-07-26 踩过）。
        "thinking": {"type": "disabled"},
    }
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    url = f"{settings.deepseek_base_url}/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            return ""
        content = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""

    # 模型可能多带字，取第一个命中的合法标签
    for tag in allowed:
        if tag in content:
            return tag
    return ""
