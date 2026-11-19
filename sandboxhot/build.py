"""生成静态站点数据：docs/data/*.json 与 docs/feed.xml。前端是纯静态页面，GitHub Pages 直接托管。"""
from __future__ import annotations

from datetime import timedelta
from xml.sax.saxutils import escape

from . import cluster
from .config import SITE_DATA_DIR, SITE_DIR, iso, now_utc, parse_iso, write_json

EXTRA_KEYS = ("venue", "pdf", "stars", "points", "comments", "discussion", "language", "cited_by", "categories")


def public_item(it: dict) -> dict:
    extra = {k: v for k, v in (it.get("extra") or {}).items() if k in EXTRA_KEYS and v}
    out = {
        "id": it["id"], "url": it["url"], "title": it["title"], "title_zh": it.get("title_zh", ""),
        "summary": it.get("summary_zh") or it.get("text", "")[:280],
        "summary_is_zh": bool(it.get("summary_zh")),
        "domain": it.get("domain", "application"), "score": it.get("score", 0), "hot": it.get("hot", 0),
        "source": it["source_name"], "source_id": it["source_id"], "kind": it["kind"],
        "published": it["published"], "added": it.get("added", it["published"]),
        "authors": it.get("authors", [])[:6], "tags": it.get("tags", []), "ai": bool(it.get("llm")),
        "cluster": it.get("cluster", it["id"]), "cluster_size": it.get("cluster_size", 1), "lead": it.get("is_lead", True),
    }
    if extra:
        out["extra"] = extra
    if it.get("brief"):
        out["brief"] = it["brief"]
    return out


def build(store, cfg: dict, sources: list[dict], log=print) -> dict:
    r = cfg["retention"]
    now = now_utc()
    selected = [it for it in store.items.values() if it.get("status") == "selected"]
    cluster.assign(selected)
    for it in selected:
        it["hot"] = cluster.hot_score(it)
    cutoff = now - timedelta(days=r["site_items_days"])
    visible = [it for it in selected if (parse_iso(it.get("added")) or now) >= cutoff]
    visible.sort(key=lambda it: it.get("added", ""), reverse=True)
    visible = visible[: r["site_items_max"]]
    items = [public_item(it) for it in visible]
    write_json(SITE_DATA_DIR / "items.json", {"generated": iso(now), "items": items}, compact=True)

    digests = {
        "daily": [{k: d[k] for k in ("key", "label", "markdown", "ai", "created")} for d in store.digests.get("daily", [])],
        "weekly": [{k: d[k] for k in ("key", "label", "markdown", "ai", "created")} for d in store.digests.get("weekly", [])],
    }
    write_json(SITE_DATA_DIR / "digests.json", digests, compact=True)

    counts: dict[str, int] = {}
    per_source: dict[str, int] = {}
    for it in items:
        counts[it["domain"]] = counts.get(it["domain"], 0) + 1
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
        "sources": src_meta, "last_run": store.runtime.get("last_run", {}),
    }
    write_json(SITE_DATA_DIR / "meta.json", meta)
    write_feed(items[:60], cfg)
    log(f"  站点数据：{len(items)} 条入选，{len(digests['daily'])} 份日报，{len(digests['weekly'])} 份周报")
    return meta


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
