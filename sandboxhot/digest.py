"""日报/周报：每天最多一次日报、每周一次周报，用写作能力更强的模型；模型不可用时生成规则版，之后有额度再补写。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from .budget import BudgetExceeded
from .config import iso, local_tz, now_utc, parse_iso, prompt
from .llm import LLM, LLMUnavailable

DOMAIN_ZH = {"academic": "学术前沿", "application": "落地应用", "business": "商业", "game": "游戏", "platform": "平台工具"}


def _items_between(store, start: datetime, end: datetime) -> list[dict]:
    out = []
    for it in store.items.values():
        if it.get("status") != "selected" or not it.get("is_lead", True):
            continue
        t = parse_iso(it.get("added"))
        if t and start <= t < end:
            out.append(it)
    weight = {"academic": 8, "application": 8}
    out.sort(key=lambda it: it.get("score", 0) + weight.get(it.get("domain"), 0), reverse=True)
    return out


def _rule_digest(items: list[dict], title: str) -> str:
    lines = [f"## {title}", "", "（模型暂不可用，以下为按分数自动排列的条目，稍后会自动改写为编辑版。）", ""]
    for dom, name in (("academic", "学术前沿"), ("application", "落地应用")):
        lines.append(f"### {name}")
        sel = [it for it in items if it.get("domain") == dom][:8]
        lines += [f"- {it.get('title_zh') or it['title']} [来源]({it['url']})" for it in sel] or ["- 本期暂无"]
        lines.append("")
    lines.append("### 商业 · 游戏 · 平台")
    sel = [it for it in items if it.get("domain") not in ("academic", "application")][:8]
    lines += [f"- {it.get('title_zh') or it['title']} [来源]({it['url']})" for it in sel] or ["- 本期暂无"]
    return "\n".join(lines)


def _make(store, cfg, llm: LLM, kind: str, key: str, start, end, label: str, log) -> bool:
    limit = cfg["digest"]["daily_items" if kind == "daily" else "weekly_items"]
    items = _items_between(store, start, end)[:limit]
    if len(items) < (3 if kind == "daily" else 5):
        return False
    lst = store.digests.setdefault(kind, [])
    existing = next((d for d in lst if d["key"] == key), None)
    if existing and (existing.get("ai") or not llm.available):
        return False
    md, ai, model = None, False, None
    if llm.available:
        material = [{"domain": DOMAIN_ZH.get(it.get("domain"), ""), "score": it.get("score"), "title": it.get("title_zh") or it["title"],
                     "summary": it.get("summary_zh") or it.get("text", "")[:240], "source": it["source_name"], "url": it["url"]}
                    for it in items]
        system = prompt("digest").replace("{{period}}", "日报" if kind == "daily" else "周报").replace(
            "{{length}}", "600" if kind == "daily" else "1200")
        user = f"{label}，共 {len(items)} 条：\n" + json.dumps(material, ensure_ascii=False)
        try:
            md, model = llm.chat("digest", system, user, max_tokens=1600 if kind == "daily" else 2800,
                                 purpose=f"digest-{kind}", stop_ratio=cfg["budget"]["digest_stop_ratio"], temperature=0.4)
            md = md.strip().removeprefix("```markdown").removeprefix("```").removesuffix("```").strip()
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
