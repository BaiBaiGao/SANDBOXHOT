"""大模型加工：批量精选（一次调用同时完成相关性、领域、打分、中文标题摘要），高价值条目的速读卡。"""
from __future__ import annotations

import json
from datetime import timedelta

from .budget import BudgetExceeded
from .config import iso, now_utc, parse_iso, prompt
from .llm import LLM, LLMUnavailable, parse_json_block
from .relevance import DOMAINS, guess_domain

FIELDS_TRIAGE = ("domain", "score", "title_zh", "summary_zh", "tags")


def _priority(it: dict) -> float:
    p = it.get("kw_score", 0)
    if it.get("kind") == "paper":
        p += 20
    if it.get("domain_guess") == "application":
        p += 10
    added = parse_iso(it.get("added"))
    if added:
        p -= min(30, (now_utc() - added).total_seconds() / 3600 / 12)
    return p


def triage_queue(store, cfg: dict, include_rule_filtered: bool = False) -> list[dict]:
    """待处理条目优先；其次是规则入选、尚未经过模型的条目（升级）。
    include_rule_filtered=True（笔记本补精选模式）时，规则淘汰的候选也交给模型复核，
    因为规则门槛偏严，学术条目常被误挡。"""
    p = cfg["pipeline"]
    pending = [it for it in store.items.values() if it.get("status") == "pending"]
    pending.sort(key=_priority, reverse=True)
    ok = lambda it: not it.get("llm") and it.get("attempts", 0) < p["max_triage_attempts"]
    upgrades = [it for it in store.items.values() if it.get("status") == "selected" and ok(it)]
    upgrades.sort(key=_priority, reverse=True)
    if include_rule_filtered:
        rest = [it for it in store.items.values() if it.get("status") == "filtered" and ok(it)]
        rest.sort(key=_priority, reverse=True)
        return (pending + upgrades + rest)[: p["max_triage_items_per_run"]]
    return (pending + upgrades[: p["upgrade_fallback_per_run"]])[: p["max_triage_items_per_run"]]


def _material(i: int, it: dict, chars: int) -> dict:
    m = {"i": i, "source": it["source_name"], "kind": it["kind"], "published": it["published"][:10],
         "title": it["title"], "text": it.get("text", "")[:chars]}
    venue = it.get("extra", {}).get("venue")
    if venue:
        m["venue"] = venue
    return m


def apply_triage(it: dict, res: dict, cfg: dict, model: str) -> None:
    th = cfg["pipeline"]["select_threshold"]
    domain = res.get("domain") if res.get("domain") in DOMAINS else it.get("domain_guess", "application")
    if it.get("kind") == "paper":
        domain = "academic"
    try:
        score = max(0, min(100, int(res.get("score", 0))))
    except (TypeError, ValueError):
        score = 0
    relevant = bool(res.get("relevant"))
    it.update({
        "llm": True, "model": model, "triaged": iso(now_utc()), "domain": domain, "score": score,
        "relevant": relevant,
        "title_zh": str(res.get("title_zh") or "")[:120],
        "summary_zh": str(res.get("summary_zh") or "")[:400],
        "tags": [str(t)[:12] for t in (res.get("tags") or [])][:4],
    })
    it["status"] = "selected" if relevant and score >= th.get(domain, 55) else "filtered"


def run_triage(store, cfg: dict, llm: LLM, log=print, include_rule_filtered: bool = False) -> dict:
    stats = {"sent": 0, "selected": 0, "filtered": 0, "failed": 0}
    if not llm.available:
        return stats
    p = cfg["pipeline"]
    queue = triage_queue(store, cfg, include_rule_filtered)
    if not queue:
        return stats
    system = prompt("triage")  # 固定前缀：每批完全相同，便于命中服务端缓存
    today = now_utc().strftime("%Y-%m-%d")
    bs = p["triage_batch_size"]
    log(f"  精选队列 {len(queue)} 条，每批 {bs} 条")
    for start in range(0, len(queue), bs):
        batch = queue[start:start + bs]
        user = f"今天是 {today}。请逐条评估以下 {len(batch)} 条材料：\n" + json.dumps(
            [_material(i, it, p["triage_text_chars"]) for i, it in enumerate(batch)], ensure_ascii=False)
        try:
            text, model = llm.chat("triage", system, user, max_tokens=220 * len(batch) + 120, purpose="triage")
        except BudgetExceeded as exc:
            log(f"  ! 额度保护：{exc}；剩余条目留到下次")
            break
        except LLMUnavailable:
            break
        stats["sent"] += len(batch)
        data = parse_json_block(text) or {}
        results = {r.get("i"): r for r in data.get("items", []) if isinstance(r, dict)}
        for i, it in enumerate(batch):
            res = results.get(i)
            if res is None:
                it["attempts"] = it.get("attempts", 0) + 1
                stats["failed"] += 1
                continue
            apply_triage(it, res, cfg, model)
            stats[it["status"]] = stats.get(it["status"], 0) + 1
    return stats


def rule_fallback(store, cfg: dict, immediate: bool) -> int:
    """模型暂不可用（校外、额度保护）时，等待超过 fallback_after_hours 的待处理条目按关键词分数决定，
    保证网站照常更新；immediate=True（没有配置密钥的纯规则模式）时立即决定。
    规则入选的条目 llm=False，之后有余额时会被自动“升级”成模型精选。"""
    p = cfg["pipeline"]
    now = now_utc()
    n = 0
    for it in store.items.values():
        if it.get("status") != "pending":
            continue
        added = parse_iso(it.get("added")) or now
        waited = now - added > timedelta(hours=p["fallback_after_hours"])
        exhausted = it.get("attempts", 0) >= p["max_triage_attempts"]
        if not (immediate or waited or exhausted):
            continue
        score = min(80, it.get("kw_score", 0))
        it.update({"llm": False, "domain": it.get("domain_guess", "application"), "score": score,
                   "tags": [], "title_zh": "", "summary_zh": ""})
        it["status"] = "selected" if score >= p["rule_select_threshold"] else "filtered"
        n += 1
    return n


def run_briefs(store, cfg: dict, llm: LLM, log=print) -> int:
    if not llm.available:
        return 0
    p = cfg["pipeline"]
    if llm.budget.ratio() >= cfg["budget"]["brief_stop_ratio"]:
        log(f"  · 本周额度已用 {llm.budget.ratio():.0%}，跳过速读卡以节省额度")
        return 0
    cands = [it for it in store.items.values()
             if it.get("status") == "selected" and it.get("llm") and not it.get("brief")
             and it.get("domain") in p["brief_domains"] and it.get("score", 0) >= p["brief_min_score"]
             and len(it.get("text", "")) >= 200]
    cands.sort(key=lambda it: it.get("score", 0), reverse=True)
    system = prompt("brief")
    done = 0
    for it in cands[: p["max_briefs_per_run"]]:
        user = json.dumps({"source": it["source_name"], "title": it["title"], "venue": it.get("extra", {}).get("venue", ""),
                           "text": it.get("text", "")[:3500]}, ensure_ascii=False)
        try:
            text, model = llm.chat("brief", system, user, max_tokens=700, purpose="brief",
                                   stop_ratio=cfg["budget"]["brief_stop_ratio"])
        except (BudgetExceeded, LLMUnavailable) as exc:
            log(f"  ! 速读卡停止：{exc}")
            break
        data = parse_json_block(text)
        if isinstance(data, dict):
            keys = ("question", "setup", "method", "findings", "validation", "limits", "reuse")
            it["brief"] = {k: str(data.get(k, "未说明"))[:300] for k in keys}
            done += 1
    return done


def ensure_domain_guess(it: dict, kw: dict) -> None:
    if "domain_guess" not in it:
        it["domain_guess"] = guess_domain(it, kw)
