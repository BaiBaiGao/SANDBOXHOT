"""零额度的本地关键词预筛与规则兜底分类。"""
from __future__ import annotations

import re

DOMAINS = ("academic", "application", "business", "game", "platform")


def _norm(text: str) -> str:
    return " " + re.sub(r"\s+", " ", text.lower()) + " "


def _hits(text: str, table: dict) -> tuple[int, list[str]]:
    total, found = 0, []
    for term, weight in table.items():
        if term.startswith("$"):
            continue
        t = term.lower()
        # 纯 ASCII 短词按词边界匹配，避免 "abm" 命中 "kabmx"
        if re.fullmatch(r"[a-z0-9\- ]+", t.strip()) and len(t.strip()) <= 6:
            if re.search(r"(?<![a-z0-9])" + re.escape(t.strip()) + r"(?![a-z0-9])", text):
                total += weight
                found.append(term.strip())
        elif t in text:
            total += weight
            found.append(term.strip())
    return total, found


def keyword_score(item: dict, kw: dict) -> dict:
    text = _norm(f"{item.get('title', '')} {item.get('title', '')} {item.get('text', '')[:3000]}")
    sim, sim_terms = _hits(text, kw.get("simulation_strong", {}))
    ai, ai_terms = _hits(text, kw.get("ai", {}))
    neg, neg_terms = _hits(text, kw.get("negative", {}))
    sim = min(sim, 70)
    ai = min(ai, 35)
    if sim == 0:
        score = 0
    elif item.get("focused"):
        score = sim + ai + 10
    else:
        score = sim + ai if ai > 0 else sim // 3
    score = max(0, min(100, score + neg))
    return {"kw_score": score, "kw_terms": (sim_terms + ai_terms)[:8]}


def guess_domain(item: dict, kw: dict) -> str:
    if item.get("kind") == "paper":
        return "academic"
    text = _norm(f"{item.get('title', '')} {item.get('text', '')[:2000]}")
    hints = kw.get("domain_hints", {})
    best, best_n = "", 0
    for dom in ("game", "business", "application", "platform"):
        n = 0
        for w in hints.get(dom, []):
            if re.search(r"(?<![a-z0-9])" + re.escape(w.lower()) + r"(?![a-z0-9])", text) if w.isascii() else w in text:
                n += 1
        if dom == "game":
            n *= 2  # 游戏词更有区分度
        if n > best_n:
            best, best_n = dom, n
    if item.get("kind") == "repo":
        return "game" if best == "game" else "platform"
    if item.get("source_group") == "game" and best in ("", "platform"):
        return "game"
    return best or "application"


def passes_prefilter(item: dict, cfg: dict) -> bool:
    p = cfg["pipeline"]
    th = p["keyword_threshold_focused"] if item.get("focused") else p["keyword_threshold"]
    return item.get("kw_score", 0) >= th
