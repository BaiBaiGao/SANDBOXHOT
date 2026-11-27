"""本地聚簇与热度（零额度）：同一事件的多来源报道合并，热度按独立来源数和时间衰减计算。"""
from __future__ import annotations

import math
import re
from datetime import timedelta

from .config import now_utc, parse_iso

STOP = set("""a an the of for and or to in on with by from at as is are be via using use new how what why your our its
this that into over about towards toward large language model models llm llms agent agents based ai simulation""".split())


AGGREGATOR_PREFIX = ("gnews-",)  # 聚合信源：一个信源里有很多家媒体
GENERIC_NAMES = set("""The This That With From Into Over After Before About Their Your What When Where Which While How Why New
Raises Raised Secures Launches Launch Unveils Announces Introduces Funding Seed Series Million Billion Startup Startups
Agent Agents Agentic Simulation Simulations Digital Twin Twins Model Models Large Language Generative Artificial
Intelligence Research Researchers Study Paper Data Platform Framework Using Based Towards Report News Google
LLM LLMs GPT AI""".split())


def is_aggregated(it: dict) -> bool:
    return str(it.get("source_id", "")).startswith(AGGREGATOR_PREFIX)


def split_publisher(it: dict) -> tuple[str, str]:
    """Google 新闻的标题形如 “标题 - 媒体名”。返回（去掉媒体名的标题，媒体名）。"""
    title = it.get("title", "")
    if it.get("publisher"):
        pub = it["publisher"]
        suffix = " - " + pub
        return (title[: -len(suffix)] if title.endswith(suffix) else title), pub
    if is_aggregated(it) and " - " in title:
        head, pub = title.rsplit(" - ", 1)
        if 0 < len(pub) <= 60:
            return head, pub
    return title, ""


def publisher_of(it: dict) -> str:
    """判断“是不是同一家来源”用的键：聚合信源按实际媒体区分，其余按信源。"""
    pub = split_publisher(it)[1]
    return f"pub:{pub.lower()}" if pub else str(it.get("source_id", ""))


def tokens(it: dict) -> set[str]:
    text = split_publisher(it)[0].lower()
    words = {w for w in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", text) if w not in STOP}
    zh = re.sub(r"[^\u4e00-\u9fff]", "", it.get("title_zh", ""))
    bigrams = {zh[i:i + 2] for i in range(len(zh) - 1)}
    return words | bigrams


def names(it: dict) -> set[str]:
    """标题里的专有名词（公司、产品、项目名），用来识别措辞不同但说的是同一件事的新闻。"""
    title = split_publisher(it)[0]
    return {w.lower() for w in re.findall(r"\b[A-Z][A-Za-z0-9]{3,}\b", title) if w not in GENERIC_NAMES}


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
    pubs = {it["id"]: publisher_of(it) for it in items}
    nm = {it["id"]: names(it) for it in recent}
    df: dict[str, int] = {}
    for it in recent:
        for w in nm[it["id"]]:
            df[w] = df.get(w, 0) + 1
    for i, a in enumerate(recent):
        for b in recent[i + 1:]:
            if pubs[a["id"]] == pubs[b["id"]] and not (is_aggregated(a) and is_aggregated(b)):
                continue  # 同一个普通信源不会把同一件事报两遍；聚合信源里同一家媒体的重复转载照样合并
            sim = jaccard(toks[a["id"]], toks[b["id"]])
            if sim >= threshold:
                parent[find(a["id"])] = find(b["id"])
                continue
            # 新闻类：标题共享一个不常见的专有名词（如公司名），一周内发布，且用词有一定重合，视为同一事件
            if "paper" in (a.get("kind"), b.get("kind")) or sim < 0.12:
                continue
            shared = {w for w in nm[a["id"]] & nm[b["id"]] if df.get(w, 0) <= 30}
            pa, pb = parse_iso(a.get("published")), parse_iso(b.get("published"))
            if shared and pa and pb and abs((pa - pb).total_seconds()) <= 7 * 86400:
                parent[find(a["id"])] = find(b["id"])
    for a, b in extra_pairs or []:
        if a in parent and b in parent:
            parent[find(a)] = find(b)
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(find(it["id"]), []).append(it)
    for members in groups.values():
        # 代表条目：优先选模型处理过的（有中文标题和摘要），再看分数和信源级别
        lead = max(members, key=lambda m: (bool(m.get("llm")), bool(m.get("read")), m.get("score", 0), m.get("tier") == "T1"))
        srcs = {pubs[m["id"]] for m in members}
        for m in members:
            m["cluster"] = lead["id"]
            m["cluster_size"] = len(srcs)
            m["is_lead"] = m is lead


# AIHOT 用 48 小时窗口、24 小时减半。本站每天只新增十条左右，论文的发布时间又常比抓到时早一两天，
# 照搬的话榜上只剩两三条，所以放宽到 7 天窗口、48 小时减半；“每个独立来源只算一次”的规则不变。
HOT_WINDOW_H = 168
HOT_HALF_LIFE_H = 48
STALE_DAYS = 10       # 发布超过 10 天的旧内容（回填论文等）不进热度


def hot_scores(items: list[dict], now=None, window_h: float = HOT_WINDOW_H, half_life_h: float = HOT_HALF_LIFE_H) -> dict[str, dict]:
    """按事件算热度（参考 AIHOT）：同一事件在窗口内每个独立来源只算一次，按首次报道时间衰减，
    再乘代表条目的分数。一家媒体发十篇也只算一次，重复抓取不会多算。

    返回 {cluster_id: {"hot", "sources"（窗口内独立来源数）, "first"（最早报道时间）}}，并把 hot 写回每个成员。"""
    now = now or now_utc()
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(it.get("cluster", it["id"]), []).append(it)
    out: dict[str, dict] = {}
    for cid, members in groups.items():
        first_by_pub: dict[str, object] = {}
        for m in members:
            if m.get("backfill"):
                continue
            t = parse_iso(m.get("added")) or now
            pub = parse_iso(m.get("published"))
            if pub and pub <= now and (now - pub) > timedelta(days=STALE_DAYS):
                continue
            if pub and pub < t:
                t = pub  # 用最早的报道时间：晚抓到的旧消息不冒充新热点
            k = publisher_of(m)
            if k not in first_by_pub or t < first_by_pub[k]:
                first_by_pub[k] = t
        heat, n, first = 0.0, 0, None
        for t in first_by_pub.values():
            age_h = max(0.0, (now - t).total_seconds() / 3600)
            if age_h > window_h:
                continue
            heat += math.pow(0.5, age_h / half_life_h)
            n += 1
            first = t if first is None or t < first else first
        lead = next((m for m in members if m.get("is_lead", True)), members[0])
        hot = round(lead.get("score", 0) * heat, 2)
        for m in members:
            m["hot"] = hot
        if n:
            out[cid] = {"hot": hot, "sources": n, "first": first}
    return out


def hot_score(it: dict) -> float:
    """单条的热度（单独调用时按只有它一个来源算）。"""
    return hot_scores([dict(it, cluster=it["id"])]).get(it["id"], {}).get("hot", 0.0)
