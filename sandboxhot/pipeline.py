"""一次完整更新：采集 → 本地预筛 → 大模型精选 → 速读卡 → 日报/周报 → 生成站点。"""
from __future__ import annotations

from datetime import timedelta

from . import collect, enrich, relevance
from .budget import Budget
from .build import build
from .config import api_key, iso, keywords, now_utc, parse_iso, settings, sources
from .digest import run_digests
from .llm import LLM
from .store import Store


def ingest(store: Store, raw: list[dict], cfg: dict, kw: dict, first_run_ids: set[str], log=print) -> dict:
    p = cfg["pipeline"]
    now = now_utc()
    max_age = timedelta(days=p["max_item_age_days"])
    stats = {"new": 0, "kept": 0, "dropped": 0, "old": 0}
    per_source_first: dict[str, int] = {}
    for it in raw:
        if store.known(it["id"]):
            continue
        stats["new"] += 1
        pub = parse_iso(it["published"]) or now
        if now - pub > max_age:
            store.seen[it["id"]] = iso(now)
            stats["old"] += 1
            continue
        it.update(relevance.keyword_score(it, kw))
        if not relevance.passes_prefilter(it, cfg):
            store.seen[it["id"]] = iso(now)
            stats["dropped"] += 1
            continue
        if it["source_id"] in first_run_ids:
            n = per_source_first.get(it["source_id"], 0)
            if n >= p["first_run_backfill_per_source"]:
                store.seen[it["id"]] = iso(now)
                continue
            per_source_first[it["source_id"]] = n + 1
        enrich.ensure_domain_guess(it, kw)
        it["added"] = iso(now)
        it["status"] = "pending"
        store.items[it["id"]] = it
        stats["kept"] += 1
    return stats


def update(*, use_llm: bool = True, force_fetch: bool = False, fetch: bool = True, require_content: bool = False, log=print) -> dict:
    cfg, kw, srcs = settings(), keywords(), sources()
    store = Store()
    budget = Budget(cfg)
    llm = LLM(cfg, budget, enabled=use_llm, log=log)
    rule_mode = use_llm and api_key() is None
    log(f"[SANDBOXHOT] {iso(now_utc())}  模型：{'可用' if llm.available else '关闭 — ' + str(llm.disabled_reason)}")
    log(f"  额度：滚动 7 天已用 {budget.spent_7d():.2f} / {budget.weekly_cap:.0f} 积分")

    stats: dict = {}
    if fetch:
        log("1) 采集")
        known_sources = set(store.runtime.get("last_fetch", {}))
        first_run_ids = {s["id"] for s in srcs if s["id"] not in known_sources}
        raw = collect.collect(srcs, store.runtime, force=force_fetch, log=log)
        if require_content and not raw and all(s["id"] in store.runtime.get("errors", {})
                                               for s in srcs if s.get("enabled", True)):
            raise RuntimeError("所有启用的信源均采集失败")
        log("2) 本地关键词预筛（不消耗积分）")
        stats["ingest"] = ingest(store, raw, cfg, kw, first_run_ids, log)
        log(f"  新条目 {stats['ingest']['new']}，进入候选 {stats['ingest']['kept']}，"
            f"不相关 {stats['ingest']['dropped']}，过旧 {stats['ingest']['old']}")

    log("3) 大模型批量精选")
    stats["triage"] = enrich.run_triage(store, cfg, llm, log)
    log(f"  {stats['triage']}")
    stats["fallback"] = enrich.rule_fallback(store, cfg, immediate=(not use_llm) or rule_mode)
    if stats["fallback"]:
        log(f"  规则兜底处理 {stats['fallback']} 条（之后有额度会自动升级为模型精选）")

    log("4) 高价值论文/应用速读卡")
    stats["briefs"] = enrich.run_briefs(store, cfg, llm, log)
    log(f"  新增速读卡 {stats['briefs']} 张")

    log("5) 日报 / 周报")
    selected = [it for it in store.items.values() if it.get("status") == "selected"]
    from . import cluster
    cluster.assign(selected)
    run_digests(store, cfg, llm, log)

    log("6) 生成站点")
    removed = store.prune(cfg)
    store.runtime["last_run"] = {"at": iso(now_utc()), "llm": llm.available, "spent_run": round(budget.run_spent, 4)}
    meta = build(store, cfg, srcs, log)
    if require_content and not meta["total"]:
        raise RuntimeError("没有可发布的真实条目")
    store.save()
    budget.save()
    log(f"完成：本次消耗约 {budget.run_spent:.4f} 积分；滚动 7 天 {budget.spent_7d():.2f} 积分；清理过期 {removed} 条")
    return stats


def enrich_only(log=print) -> int:
    """笔记本模式：不采集、不改网站文件，只用同济 API 给云端已采集的条目补模型精选、速读卡和日报，
    结果写入 data/enrichments.json。云端 GitHub Actions 下次构建时自动合并。"""
    cfg = settings()
    store = Store()
    budget = Budget(cfg)
    llm = LLM(cfg, budget, log=log)
    log(f"[SANDBOXHOT enrich] {iso(now_utc())}  额度：滚动 7 天已用 {budget.spent_7d():.2f} / {budget.weekly_cap:.0f} 积分")
    if not llm.available:
        log(f"  模型不可用：{llm.disabled_reason}")
        return 1
    try:
        llm.list_models()  # 免费的连通性探测：校外没连 VPN 时立即结束，不浪费时间
    except Exception as exc:  # noqa: BLE001
        log(f"  连不上同济平台（校外请先连学校 VPN）：{str(exc)[:160]}")
        return 1
    log("1) 模型精选（含复核规则淘汰的候选）")
    log(f"  {enrich.run_triage(store, cfg, llm, log, include_rule_filtered=True)}")
    log("2) 高价值论文/应用速读卡")
    log(f"  新增 {enrich.run_briefs(store, cfg, llm, log)} 张")
    log("3) 日报 / 周报")
    from . import cluster
    cluster.assign([it for it in store.items.values() if it.get("status") == "selected"])
    run_digests(store, cfg, llm, log)
    out = store.save_enrichments(cfg)
    budget.save()
    log(f"完成：模型精选 {len(out['triage'])} 条，速读卡 {len(out['briefs'])} 张，"
        f"AI 日报 {len(out['digests']['daily'])} 份；本次约 {budget.run_spent:.4f} 积分，滚动 7 天 {budget.spent_7d():.2f} 积分")
    return 0


def rebuild(log=print) -> None:
    cfg, srcs = settings(), sources()
    store = Store()
    build(store, cfg, srcs, log)
    store.save()
