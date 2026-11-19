"""主题研判（每个主题每周一段趋势判断）与横纵专题报告（参考“横纵分析法”：纵轴讲演进，横轴比路线，交汇给判断）。
用 512K 上下文的长文模型；按 budget.allow('normal') 匀速花费。"""
from __future__ import annotations

import json
from datetime import timedelta

from .budget import BudgetExceeded
from .config import iso, now_utc, parse_iso, prompt, topics
from .llm import LLM, LLMUnavailable, tidy
from .relevance import item_topics


def _pub(it: dict):
    return parse_iso(it.get("published")) or parse_iso(it.get("added")) or now_utc()


def topic_items(store, slug: str, defs: list[dict]) -> list[dict]:
    return [it for it in store.items.values()
            if it.get("status") == "selected" and slug in item_topics(it, defs)]


def _material(it: dict, full: bool = False) -> dict:
    read = it.get("read") or {}
    m = {"date": it["published"][:10], "title": it.get("title_zh") or it["title"], "original_title": it["title"],
         "source": it["source_name"], "domain": it.get("domain"), "score": it.get("score"),
         "summary": it.get("summary_zh") or it.get("text", "")[:300], "url": it["url"]}
    if read.get("why"):
        m["why"] = read["why"]
    if read.get("validation"):
        m["validation"] = read["validation"]
    if full:
        venue = (it.get("extra") or {}).get("venue")
        if venue:
            m["venue"] = venue
        if read.get("resources"):
            m["resources"] = [f"{r['type']}: {r['url']}" for r in read["resources"]]
        b = it.get("brief") or {}
        for k in ("setup", "findings", "limits"):
            if b.get(k) and b[k] != "未说明":
                m[k] = b[k]
    return m


def _md_title(md: str, fallback: str) -> str:
    for line in md.splitlines():
        if line.startswith("## "):
            return line[3:].strip()[:80]
    return fallback


def run_topic_analyses(store, cfg: dict, llm: LLM, log=print) -> int:
    r = cfg["research"]
    defs = topics()
    now = now_utc()
    done = 0
    order = sorted(defs, key=lambda t: (store.topic_analyses.get(t["slug"]) or {}).get("created", ""))
    for t in order:
        if done >= r["topics_per_run"]:
            break
        last = parse_iso((store.topic_analyses.get(t["slug"]) or {}).get("created"))
        if last and now - last < timedelta(days=r["topic_every_days"]):
            continue
        window = now - timedelta(days=r["topic_window_days"])
        items = [it for it in topic_items(store, t["slug"], defs) if _pub(it) >= window]
        if len(items) < r["topic_min_items"]:
            continue
        if not llm.available or not llm.budget.allow("normal"):
            log(f"  · 主题研判：额度进度 {llm.budget.pace():.0%}，暂停")
            break
        items.sort(key=lambda it: it.get("score", 0), reverse=True)
        items = sorted(items[:40], key=_pub, reverse=True)
        system = prompt("topic", topic_name=t["name"], topic_definition=t["definition"])
        user = f"最近 {r['topic_window_days']} 天收录 {len(items)} 条：\n" + json.dumps([_material(it) for it in items], ensure_ascii=False)
        try:
            md, model = llm.chat("topic", system, user, max_tokens=3000, purpose="topic", timeout=300, temperature=0.3)
        except (BudgetExceeded, LLMUnavailable) as exc:
            log(f"  ! 主题研判停止：{exc}")
            break
        if md.strip():
            store.topic_analyses[t["slug"]] = {"markdown": tidy(md.strip()), "created": iso(now), "model": model,
                                               "item_ids": [it["id"] for it in items], "window_days": r["topic_window_days"]}
            done += 1
            log(f"  · 主题研判：{t['name']}（{len(items)} 条）")
    return done


def run_reports(store, cfg: dict, llm: LLM, log=print) -> int:
    r = cfg["research"]
    defs = topics()
    now = now_utc()
    recent = [x for x in store.research if (parse_iso(x.get("created")) or now) > now - timedelta(days=7)]
    if len(recent) >= r["reports_per_week"]:
        return 0
    last_by_topic: dict[str, object] = {}
    for x in store.research:
        c = parse_iso(x.get("created"))
        if c and (x["topic"] not in last_by_topic or c > last_by_topic[x["topic"]]):
            last_by_topic[x["topic"]] = c
    cands = []
    for t in defs:
        last = last_by_topic.get(t["slug"])
        if last and now - last < timedelta(days=r["report_repeat_days"]):
            continue
        items = topic_items(store, t["slug"], defs)
        if len(items) >= r["report_min_items"]:
            cands.append((len(items), t, items))
    cands.sort(key=lambda c: -c[0])
    done = 0
    for _, t, items in cands[: r["reports_per_week"] - len(recent)]:
        if not llm.available or not llm.budget.allow("normal"):
            log(f"  · 专题报告：额度进度 {llm.budget.pace():.0%}，暂停")
            break
        items.sort(key=lambda it: it.get("score", 0), reverse=True)
        items = sorted(items[: r["report_max_items"]], key=_pub)
        system = prompt("research", topic_name=t["name"], topic_definition=t["definition"])
        user = (f"档案中“{t['name']}”共 {len(items)} 条（时间范围 {items[0]['published'][:10]} 至 {items[-1]['published'][:10]}）：\n"
                + json.dumps([_material(it, full=True) for it in items], ensure_ascii=False))
        try:
            md, model = llm.chat("research", system, user, max_tokens=9000, purpose="research", timeout=900, temperature=0.3)
        except (BudgetExceeded, LLMUnavailable) as exc:
            log(f"  ! 专题报告停止：{exc}")
            break
        if len(md.strip()) < 400:
            continue
        key = f"{t['slug']}-{now.strftime('%Y%m%d')}"
        store.research = [x for x in store.research if x["key"] != key]
        store.research.append({"key": key, "topic": t["slug"], "topic_name": t["name"], "title": _md_title(md, t["name"]),
                               "markdown": tidy(md.strip()), "created": iso(now), "model": model,
                               "item_ids": [it["id"] for it in items],
                               "span": [items[0]["published"][:10], items[-1]["published"][:10]]})
        done += 1
        log(f"  · 横纵专题：{t['name']}（{len(items)} 条）")
    return done
