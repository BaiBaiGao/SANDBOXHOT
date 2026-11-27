"""日报/周报：每天最多一次日报、每周一次周报，用写作能力更强的模型；模型不可用时生成规则版，之后有额度再补写。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from .budget import BudgetExceeded
from .config import iso, local_tz, now_utc, parse_iso, prompt
from .llm import LLM, LLMUnavailable, tidy

DOMAIN_ZH = {"academic": "学术前沿", "application": "落地应用", "business": "商业", "game": "游戏", "platform": "平台工具"}


def _substantive(it: dict) -> bool:
    """材料够不够写一条：只有标题、没有摘要的（比如部分 Google 新闻）不进日报周报。"""
    return bool(it.get("summary_zh")) or len((it.get("text") or "").strip()) >= 80


def _reported(store, kind: str, key: str) -> dict[str, datetime]:
    """之前各期（同类、不含本期）已经报过的事件 → 最近一次报道它的时间。"""
    seen: dict[str, datetime] = {}
    for d in store.digests.get(kind, []):
        if d["key"] >= key:
            continue
        at = parse_iso(d.get("created")) or now_utc()
        for iid in d.get("item_ids", []):
            it = store.items.get(iid)
            cid = (it or {}).get("cluster", iid)
            if cid not in seen or at > seen[cid]:
                seen[cid] = at
    return seen


def _items_between(store, start: datetime, end: datetime, reported: dict | None = None) -> list[dict]:
    """一件事一条（只取事件的代表条目）；报过的事只有在之后又有新来源时才跟进。"""
    reported = reported or {}
    clusters: dict[str, list[dict]] = {}
    for it in store.items.values():
        if it.get("status") == "selected":
            clusters.setdefault(it.get("cluster", it["id"]), []).append(it)
    out = []
    for it in store.items.values():
        if it.get("status") != "selected" or not it.get("is_lead", True) or not _substantive(it):
            continue
        cid = it.get("cluster", it["id"])
        if cid in reported and not any((parse_iso(m.get("added")) or start) > reported[cid] for m in clusters.get(cid, [])):
            continue
        t = parse_iso(it.get("added"))
        pub = parse_iso(it.get("published")) or t
        # 回填进来的旧论文不进日报/周报：发布时间要在窗口开始前 10 天以内
        if t and start <= t < end and not it.get("backfill") and pub and pub >= start - timedelta(days=10):
            out.append(it)
    weight = {"academic": 8, "application": 8}
    out.sort(key=lambda it: it.get("score", 0) + weight.get(it.get("domain"), 0), reverse=True)
    return out


def _rule_digest(items: list[dict], title: str) -> str:
    """规则版：按分数排列，没有条目的栏目整栏省略。"""
    lines = [f"## {title}", "", "（模型暂不可用，以下为按分数自动排列的条目，稍后会自动改写为编辑版。）", ""]
    groups = (("学术前沿", lambda d: d == "academic"), ("落地应用", lambda d: d == "application"),
              ("商业 · 游戏 · 平台", lambda d: d not in ("academic", "application")))
    for name, pick in groups:
        sel = [it for it in items if pick(it.get("domain"))][:8]
        if not sel:
            continue
        lines.append(f"### {name}")
        lines += [f"- {it.get('title_zh') or it['title']} [来源]({it['url']})" for it in sel]
        lines.append("")
    return "\n".join(lines).rstrip()


def _make(store, cfg, llm: LLM, kind: str, key: str, start, end, label: str, log) -> bool:
    limit = cfg["digest"]["daily_items" if kind == "daily" else "weekly_items"]
    items = _items_between(store, start, end, _reported(store, kind, key))[:limit]
    if len(items) < (3 if kind == "daily" else 5):
        return False
    lst = store.digests.setdefault(kind, [])
    existing = next((d for d in lst if d["key"] == key), None)
    if existing and (existing.get("ai") or not llm.available):
        return False
    md, ai, model = None, False, None
    if llm.available:
        material = [{"domain": DOMAIN_ZH.get(it.get("domain"), ""), "score": it.get("score"), "title": it.get("title_zh") or it["title"],
                     "summary": it.get("summary_zh") or it.get("text", "")[:240], "why": (it.get("read") or {}).get("why", ""),
                     "resources": [r["url"] for r in (it.get("read") or {}).get("resources", [])][:3],
                     "source": it["source_name"], "url": it["url"]}
                    for it in items]
        system = prompt("digest").replace("{{period}}", "日报" if kind == "daily" else "周报").replace(
            "{{length}}", "900" if kind == "daily" else "1800")
        user = f"{label}，共 {len(items)} 条：\n" + json.dumps(material, ensure_ascii=False)
        try:
            md, model = llm.chat("digest" if kind == "daily" else "weekly", system, user,
                                 max_tokens=2400 if kind == "daily" else 4500, timeout=300,
                                 purpose=f"digest-{kind}", stop_ratio=cfg["budget"]["digest_stop_ratio"], temperature=0.4)
            md = tidy(md.strip().removeprefix("```markdown").removeprefix("```").removesuffix("```").strip())
            ai = bool(md)
        except (BudgetExceeded, LLMUnavailable) as exc:
            log(f"  ! {label}改用规则版：{exc}")
    if not md:
        md = _rule_digest(items, label)
    entry = {"key": key, "label": label, "markdown": md, "ai": ai, "model": model, "item_ids": [it["id"] for it in items],
             "created": iso(now_utc())}
    if existing:
        lst.remove(existing)
    lst.append(entry)
    log(f"  · 生成{label}（{'模型' if ai else '规则'}版，{len(items)} 条）")
    return True


def run_digests(store, cfg: dict, llm: LLM, log=print) -> None:
    tz = local_tz(cfg)
    today = now_utc().astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    # 日报：最近 3 个完整自然日（缺失的补齐；规则版在模型可用时改写）
    for back in (1, 2, 3):
        day = today - timedelta(days=back)
        _make(store, cfg, llm, "daily", day.strftime("%Y-%m-%d"), day, day + timedelta(days=1),
              f"{day.month} 月 {day.day} 日日报", log)
    # 周报：上一个完整周（周一至周日）
    monday = today - timedelta(days=today.weekday())
    start = monday - timedelta(days=7)
    y, w, _ = start.isocalendar()
    _make(store, cfg, llm, "weekly", f"{y}-W{w:02d}", start, monday,
          f"{y} 年第 {w} 周周报（{start.month}.{start.day}–{(monday - timedelta(days=1)).month}.{(monday - timedelta(days=1)).day}）", log)
