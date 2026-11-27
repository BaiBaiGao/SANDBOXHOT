"""生成静态站点数据：docs/data/*.json 与 docs/feed.xml。前端是纯静态页面，GitHub Pages 直接托管。"""
from __future__ import annotations

from datetime import timedelta
from xml.sax.saxutils import escape

from . import cluster
from .config import SITE_DATA_DIR, SITE_DIR, iso, now_utc, parse_iso, read_json, topics, write_json
from .relevance import item_topics

EXTRA_KEYS = ("venue", "pdf", "stars", "points", "comments", "discussion", "language", "cited_by", "categories")


def _plain_summary(it: dict, title: str) -> str:
    """没有中文摘要时用原文摘要；Google 新闻的“摘要”只是标题加媒体名，和标题重复就不显示。"""
    text = it.get("text", "")[:280]
    norm = lambda x: "".join(ch for ch in x.lower() if ch.isalnum())
    if title and norm(text).startswith(norm(title)[:60]):
        return ""
    return text


def public_item(it: dict, defs: list[dict]) -> dict:
    extra = {k: v for k, v in (it.get("extra") or {}).items() if k in EXTRA_KEYS and v}
    read = it.get("read") or {}
    title, pub = cluster.split_publisher(it)
    out = {
        "id": it["id"], "url": it["url"], "title": title, "title_zh": it.get("title_zh", ""),
        "summary": it.get("summary_zh") or _plain_summary(it, title),
        "summary_is_zh": bool(it.get("summary_zh")),
        "domain": it.get("domain", "application"), "score": it.get("score", 0), "hot": it.get("hot", 0),
        "source": f"{pub}（Google 新闻）" if pub else it["source_name"], "source_id": it["source_id"], "kind": it["kind"],
        "published": it["published"], "added": it.get("added", it["published"]),
        "authors": it.get("authors", [])[:6], "tags": it.get("tags", []), "ai": bool(it.get("llm")),
        "topics": item_topics(it, defs),
        "cluster": it.get("cluster", it["id"]), "cluster_size": it.get("cluster_size", 1), "lead": it.get("is_lead", True),
    }
    if extra:
        out["extra"] = extra
    if read.get("why"):
        out["why"] = read["why"]
    if read.get("validation") and read["validation"] != "unclear":
        out["validation"] = read["validation"]
    if read.get("resources"):
        out["res"] = len(read["resources"])
    if it.get("brief"):
        out["brief"] = 1
    if read.get("abstract_zh"):
        out["read"] = 1
    if it.get("backfill"):
        out["backfill"] = 1
    if it.get("applied") and out["domain"] != "application":
        out["applied"] = 1  # 有真实场景应用的论文等，同时出现在“实际应用”板块
    return out


def detail(it: dict, story: dict | None, two_scores: bool) -> dict:
    read = it.get("read") or {}
    d = {"text": it.get("text", "")[:2500], "authors": it.get("authors", [])}
    for k in ("abstract_zh", "why", "resources", "validation"):
        if read.get(k):
            d[k] = read[k]
    if it.get("brief"):
        d["brief"] = it["brief"]
    if it.get("related"):
        d["related"] = it["related"]
    if story:
        d["story"] = story["text"]
    if two_scores and "score2" in it:
        d["scores"] = [it.get("score1"), it.get("score2")]
    models = [m for m in (it.get("model"), it.get("model2"), read.get("model")) if m]
    if models:
        d["models"] = sorted(set(models))
    return d


def build(store, cfg: dict, sources: list[dict], log=print) -> dict:
    r = cfg["retention"]
    now = now_utc()
    defs = topics()
    selected = [it for it in store.items.values() if it.get("status") == "selected"]
    cluster.assign(selected, extra_pairs=getattr(store, "dupes", []))
    heat = cluster.hot_scores(selected, now)
    cutoff = now - timedelta(days=r["site_items_days"])
    visible = [it for it in selected if (parse_iso(it.get("added")) or now) >= cutoff]
    visible.sort(key=lambda it: it.get("published", ""), reverse=True)
    visible = visible[: r["site_items_max"]]
    items = [public_item(it, defs) for it in visible]
    visible_ids = {it["id"] for it in visible}
    write_json(SITE_DATA_DIR / "items.json", {"generated": iso(now), "items": items}, compact=True)
    write_extras(store, cfg, visible, items, visible_ids, defs, now)
    write_hot(heat, {it["id"]: it for it in selected}, visible_ids, now)

    digests = {
        "daily": [{k: d[k] for k in ("key", "label", "markdown", "ai", "created")} for d in store.digests.get("daily", [])],
        "weekly": [{k: d[k] for k in ("key", "label", "markdown", "ai", "created")} for d in store.digests.get("weekly", [])],
    }
    write_json(SITE_DATA_DIR / "digests.json", digests, compact=True)

    counts: dict[str, int] = {}
    per_source: dict[str, int] = {}
    for it in items:
        counts[it["domain"]] = counts.get(it["domain"], 0) + 1
        if it.get("applied"):
            counts["application"] = counts.get("application", 0) + 1
        per_source[it["source_id"]] = per_source.get(it["source_id"], 0) + 1
    errors = store.runtime.get("errors", {})
    src_meta = [{
        "id": s["id"], "name": s["name"], "kind": s["kind"], "group": s.get("group", ""), "tier": s.get("tier", ""),
        "enabled": s.get("enabled", True), "items": per_source.get(s["id"], 0),
        "home": s.get("url", "") if s["kind"] == "rss" else "", "query": s.get("query", ""),
        "ok": s["id"] not in errors,
    } for s in sources]
    meta = {
        "site": cfg["site"], "generated": iso(now), "counts": counts, "total": len(items),
        "reads": sum(1 for it in items if it.get("read")), "research": len(getattr(store, "research", [])),
        "ai_items": sum(1 for it in items if it["ai"]),
        "sources": src_meta, "last_run": store.runtime.get("last_run", {}),
        "funnel": funnel(store, sources, now),
    }
    write_json(SITE_DATA_DIR / "meta.json", meta)
    write_feed(items[:60], cfg)
    log(f"  站点数据：{len(items)} 条入选，{len(digests['daily'])} 份日报，{len(digests['weekly'])} 份周报")
    return meta


def funnel(store, sources: list[dict], now) -> dict:
    """关于页的“信源 → 收录 → 精选 → 成刊”四个数字（近 7 天）。"""
    week = now - timedelta(days=7)
    recent = lambda ts: (parse_iso(ts) or week) > week
    added = [it for it in store.items.values() if recent(it.get("added"))]
    # 被预筛挡掉的只记在 seen 里；进了 items 的不在 seen 里
    dropped = sum(1 for iid, ts in store.seen.items() if iid not in store.items and recent(ts))
    digests = sum(1 for k in ("daily", "weekly") for d in store.digests.get(k, []) if recent(d.get("created")))
    return {"sources": sum(1 for s in sources if s.get("enabled", True)), "collected_7d": len(added) + dropped,
            "kept_7d": len(added), "selected_7d": sum(1 for it in added if it.get("status") == "selected"),
            "digests_7d": digests}


HOT_MAX = 30
HOT_HISTORY_H = 48
TREND_GAP_H = 6


def write_hot(heat: dict, by_id: dict, visible_ids: set, now) -> None:
    """热点榜：按事件热度排名，并和约 6 小时前的排名比较，标出“新”和“上升”。
    历史排名就存在上一次发布的 hot.json 里（滚动保留 48 小时），不需要额外的数据文件。"""
    path = SITE_DATA_DIR / "hot.json"
    prev = read_json(path, {}) if path.exists() else {}
    history = [h for h in prev.get("history", []) if (parse_iso(h.get("t")) or now) > now - timedelta(hours=HOT_HISTORY_H)]
    base = next((h for h in reversed(history) if (parse_iso(h["t"]) or now) <= now - timedelta(hours=TREND_GAP_H)), None)
    ranked = sorted(((cid, v) for cid, v in heat.items() if cid in visible_ids and v["hot"] > 0),
                    key=lambda x: x[1]["hot"], reverse=True)[:HOT_MAX]
    rows = []
    for rank, (cid, v) in enumerate(ranked, 1):
        members = [iid for iid, it in by_id.items() if it.get("cluster", iid) == cid]
        trend = ""
        if (now - v["first"]).total_seconds() <= TREND_GAP_H * 3600:
            trend = "new"  # 首报 6 小时内
        elif base is not None:
            old = [base["ranks"][m] for m in members if m in base["ranks"]]
            old_src = [base.get("sources", {}).get(m, 0) for m in members]
            if not old:
                trend = "new"  # 6 小时前还不在榜上
            elif min(old) - rank >= 2 or v["sources"] > max(old_src or [0]):
                trend = "up"  # 名次上升 2 位以上，或者有新来源加入讨论
        rows.append({"id": cid, "rank": rank, "hot": v["hot"], "sources": v["sources"], "first": iso(v["first"]), "trend": trend})
    snap = {"t": iso(now), "ranks": {r["id"]: r["rank"] for r in rows}, "sources": {r["id"]: r["sources"] for r in rows}}
    if not history or (parse_iso(history[-1]["t"]) or now) <= now - timedelta(minutes=30):
        history.append(snap)
    write_json(path, {"generated": iso(now), "window_h": cluster.HOT_WINDOW_H, "half_life_h": cluster.HOT_HALF_LIFE_H,
                      "compare_h": TREND_GAP_H, "list": rows, "history": history}, compact=True)


def write_extras(store, cfg: dict, visible: list[dict], items: list[dict], visible_ids: set, defs: list[dict], now) -> None:
    """详情分片、主题、专题、资源库、给 Agent 的接口。"""
    stories = getattr(store, "stories", {})
    by_cluster: dict[str, dict] = {}
    for it in visible:
        if it["id"] in stories:
            by_cluster[it.get("cluster", it["id"])] = stories[it["id"]]
    shards: dict[str, dict] = {c: {} for c in "0123456789abcdef"}
    for it in visible:
        d = detail(it, by_cluster.get(it.get("cluster", it["id"])), True)
        if d.get("related"):
            d["related"] = [x for x in d["related"] if x in visible_ids]
        c = it["id"][0].lower()
        shards[c if c in shards else "0"][it["id"]] = d
    for c, data in shards.items():
        write_json(SITE_DATA_DIR / "details" / f"{c}.json", data, compact=True)

    analyses = getattr(store, "topic_analyses", {})
    month_ago = now - timedelta(days=30)
    tlist = []
    for t in defs:
        members = [x for x in items if t["slug"] in x["topics"]]
        a = analyses.get(t["slug"])
        tlist.append({"slug": t["slug"], "name": t["name"], "definition": t["definition"], "count": len(members),
                      "count_30d": sum(1 for x in members if (parse_iso(x["published"]) or now) >= month_ago),
                      "analysis": {"markdown": a["markdown"], "created": a["created"]} if a else None})
    write_json(SITE_DATA_DIR / "topics.json", {"topics": tlist}, compact=True)

    research = sorted(getattr(store, "research", []), key=lambda x: x["created"], reverse=True)
    write_json(SITE_DATA_DIR / "research.json", {"reports": [
        {k: x.get(k) for k in ("key", "topic", "topic_name", "title", "markdown", "created", "span")}
        | {"item_ids": [i for i in x.get("item_ids", []) if i in visible_ids]} for x in research]}, compact=True)

    seen, res = set(), []
    for it in visible:
        read = it.get("read") or {}
        rows = list(read.get("resources") or [])
        if it["kind"] == "repo":
            rows.insert(0, {"type": "code", "name": it["title"], "url": it["url"]})
        for rr in rows:
            if rr["url"] in seen:
                continue
            seen.add(rr["url"])
            res.append({"type": rr["type"], "name": rr["name"], "url": rr["url"], "item": it["id"],
                        "title": it.get("title_zh") or it["title"], "published": it["published"][:10],
                        "topics": item_topics(it, defs), "stars": (it.get("extra") or {}).get("stars", 0)})
    write_json(SITE_DATA_DIR / "resources.json", {"resources": res}, compact=True)

    latest = sorted(items, key=lambda x: x["published"], reverse=True)[:120]
    daily = sorted(store.digests.get("daily", []), key=lambda d: d["key"], reverse=True)[:1]
    api = {"generated": iso(now), "site": cfg["site"]["name"],
           "items": [{k: x.get(k) for k in ("id", "title", "title_zh", "summary", "url", "domain", "score", "topics",
                                             "published", "source", "why")} for x in latest],
           "latest_digest": {k: daily[0][k] for k in ("key", "label", "markdown")} if daily else None,
           "topics": [{"slug": t["slug"], "name": t["name"], "count": t["count"]} for t in tlist]}
    write_json(SITE_DIR / "api" / "latest.json", api, compact=True)
    (SITE_DIR / "llms.txt").write_text(LLMS_TXT.format(name=cfg["site"]["name"], tagline=cfg["site"]["tagline"],
                                                        updated=iso(now), n=len(items)), encoding="utf-8")


LLMS_TXT = """# {name}

> {tagline}

本站是纯静态网站，所有数据都是公开的 JSON 文件，Agent 可以直接读取（相对于网站根目录）：

- api/latest.json：最新 120 条精选（中文标题、摘要、领域、分数、主题、链接）和最新一期日报
- data/items.json：全部在展条目（列表字段）
- data/details/<id 首字符>.json：条目详情（中文精读、速读卡、资源、相关推荐）
- data/hot.json：热点榜（按事件热度排名，标出新上榜和上升）
- data/digests.json：日报与周报（Markdown）
- data/topics.json：主题与每周主题研判
- data/research.json：横纵专题研究报告
- data/resources.json：代码、数据集、基准等资源库
- feed.xml：RSS

领域：academic 学术论文、application 实际应用、business 商业、game 游戏、platform 平台工具。
分数 0–100 是编辑评估的阅读价值，不代表真伪；引用前请打开原文核对。

更新于 {updated}，共 {n} 条。
"""


def write_feed(items: list[dict], cfg: dict) -> None:
    site = cfg["site"]
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0"><channel>',
             f"<title>{escape(site['name'])}</title>", "<link>./</link>",
             f"<description>{escape(site['tagline'])}</description>"]
    for it in items:
        title = it["title_zh"] or it["title"]
        parts.append("<item>"
                     f"<title>{escape(title)}</title><link>{escape(it['url'])}</link>"
                     f"<guid isPermaLink=\"false\">{it['id']}</guid>"
                     f"<category>{escape(it['domain'])}</category>"
                     f"<description>{escape(it['summary'])}</description>"
                     "</item>")
    parts.append("</channel></rss>")
    (SITE_DIR / "feed.xml").write_text("\n".join(parts) + "\n", encoding="utf-8")
