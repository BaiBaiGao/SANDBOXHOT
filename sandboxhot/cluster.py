"""本地聚簇与热度（零额度）：同一事件的多来源报道合并，热度按独立来源数和时间衰减计算。"""
from __future__ import annotations

import math
import re
from datetime import timedelta

from .config import now_utc, parse_iso

STOP = set("""a an the of for and or to in on with by from at as is are be via using use new how what why your our its
this that into over about towards toward large language model models llm llms agent agents based ai simulation""".split())


def tokens(it: dict) -> set[str]:
    text = f"{it.get('title', '')}".lower()
    words = {w for w in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", text) if w not in STOP}
    zh = re.sub(r"[^一-鿿]", "", it.get("title_zh", ""))
    bigrams = {zh[i:i + 2] for i in range(len(zh) - 1)}
    return words | bigrams


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def assign(items: list[dict], window_days: int = 10, threshold: float = 0.5, extra_pairs: list | None = None) -> None:
    """extra_pairs：笔记本用 embedding 找到的跨来源同事件配对（enrichments.json 的 dupes）。"""
    now = now_utc()
    recent = [it for it in items if (parse_iso(it.get("added")) or now) > now - timedelta(days=window_days)]
    parent = {it["id"]: it["id"] for it in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    toks = {it["id"]: tokens(it) for it in recent}
    for i, a in enumerate(recent):
        for b in recent[i + 1:]:
            if a["source_id"] == b["source_id"]:
                continue
            if jaccard(toks[a["id"]], toks[b["id"]]) >= threshold:
                parent[find(a["id"])] = find(b["id"])
    for a, b in extra_pairs or []:
        if a in parent and b in parent:
            parent[find(a)] = find(b)
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(find(it["id"]), []).append(it)
    for members in groups.values():
        lead = max(members, key=lambda m: (m.get("score", 0), m.get("tier") == "T1"))
        srcs = {m["source_id"] for m in members}
        for m in members:
            m["cluster"] = lead["id"]
            m["cluster_size"] = len(srcs)
            m["is_lead"] = m is lead


def hot_score(it: dict, half_life_hours: float = 72) -> float:
    now = now_utc()
    t = parse_iso(it.get("added")) or now
    pub = parse_iso(it.get("published")) or t
    ref = pub if pub <= now else t  # 按发布时间衰减：回填的旧论文不会冒充热点
    age_h = max(0.0, (now - ref).total_seconds() / 3600)
    boost = 1 + 0.35 * (it.get("cluster_size", 1) - 1)
    weight = {"academic": 1.1, "application": 1.1}.get(it.get("domain"), 1.0)
    return round(it.get("score", 0) * boost * weight * math.pow(0.5, age_h / half_life_hours), 2)
