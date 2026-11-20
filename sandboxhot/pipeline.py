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
        if now - pub > max_age and not it.get("backfill"):
            store.seen[it["id"]] = iso(now)
            stats["old"] += 1
            continue
        it.update(relevance.keyword_score(it, kw))
        if not relevance.passes_prefilter(it, cfg):
            store.seen[it["id"]] = iso(now)
            stats["dropped"] += 1
            continue
        if it["source_id"] in first_run_ids and not it.get("backfill"):
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

    log("4) 中文精读与速读卡")
    stats["reads"] = enrich.run_reads(store, cfg, llm, log)
    stats["briefs"] = enrich.run_briefs(store, cfg, llm, log)
    log(f"  新增速读卡 {stats['briefs']} 张")

    log("5) 日报 / 周报")
    selected = [it for it in store.items.values() if it.get("status") == "selected"]
    from . import cluster
    cluster.assign(selected, extra_pairs=store.dupes)
    run_digests(store, cfg, llm, log)

    log("6) 生成站点")
    removed = store.prune(cfg)
    store.runtime["last_run"] = {"at": iso(now_utc()), "llm": llm.available, "spent_run": round(budget.run_spent, 4)}
    meta = build(store, cfg, srcs, log)
    if require_content and not meta["total"]:
        raise RuntimeError("没有可发布的真实条目")
    store.save()
    if use_llm and not rule_mode:
        store.save_enrichments(cfg)  # 本地完整模式：模型结果同样写入 enrichments.json（云端 --no-llm 不写）
    budget.save()
    log(f"完成：本次消耗约 {budget.run_spent:.4f} 积分；滚动 7 天 {budget.spent_7d():.2f} 积分；清理过期 {removed} 条")
    return stats


def enrich_only(log=print) -> int:
    """笔记本模式：不采集、不改网站文件，只用同济 API 加工云端已采集的条目，结果写入 data/enrichments.json。
    按优先级执行，受单次上限、滚动 7 天上限、匀速花费和时间预算共同约束：
    精选 > 双评 > 新条目精读 > 相关推荐 > 事件综述 > 日报周报 > 主题研判 > 横纵专题 > 新条目速读卡 > 历史回填。"""
    from . import cluster, research
    cfg = settings()
    store = Store()
    budget = Budget(cfg)
    llm = LLM(cfg, budget, log=log)
    log(f"[SANDBOXHOT enrich] {iso(now_utc())}  额度：滚动 7 天已用 {budget.spent_7d():.2f} / {budget.weekly_cap:.0f} 积分，"
        f"近 24 小时进度 {budget.pace():.0%}（每日目标 {budget.daily_target:.0f}）")
    if not llm.available:
        log(f"  模型不可用：{llm.disabled_reason}")
        return 1
    try:
        llm.list_models()  # 免费的连通性探测：校外没连 VPN 时立即结束，不浪费时间
    except Exception as exc:  # noqa: BLE001
        log(f"  连不上同济平台（校外请先连学校 VPN）：{str(exc)[:160]}")
        return 1

    def selected():
        return [it for it in store.items.values() if it.get("status") == "selected"]

    steps = [
        ("1) 模型精选（含复核规则淘汰的候选）", lambda: enrich.run_triage(store, cfg, llm, log, include_rule_filtered=True)),
        ("2) 双评复核边界条目", lambda: enrich.run_second(store, cfg, llm, log)),
        ("2b) 补标真实场景应用", lambda: enrich.run_applied(store, cfg, llm, log)),
        ("3) 新条目中文精读", lambda: (cluster.assign(selected(), extra_pairs=store.dupes),
                                   enrich.run_reads(store, cfg, llm, log, "new"))[1]),
        ("4) embedding 相关推荐与同事件识别", lambda: enrich.run_embeddings(store, cfg, llm, log)),
        ("5) 事件综述", lambda: (cluster.assign(selected(), extra_pairs=store.dupes), enrich.run_stories(store, cfg, llm, log))[1]),
        ("6) 日报 / 周报", lambda: run_digests(store, cfg, llm, log)),
        ("7) 主题研判", lambda: research.run_topic_analyses(store, cfg, llm, log)),
        ("8) 横纵专题报告", lambda: research.run_reports(store, cfg, llm, log)),
        ("9) 新条目速读卡", lambda: enrich.run_briefs(store, cfg, llm, log, "new")),
        ("10) 历史回填：精读", lambda: enrich.run_reads(store, cfg, llm, log, "backfill")),
        ("11) 历史回填：速读卡", lambda: enrich.run_briefs(store, cfg, llm, log, "backfill")),
    ]
    for title, fn in steps:
        if not llm.available:
            log(f"{title}：跳过（{llm.disabled_reason}）")
            continue
        log(title)
        try:
            res = fn()
        except Exception as exc:  # noqa: BLE001 —— 单个步骤出错不影响已完成的结果被保存
            log(f"  ! {title} 出错：{str(exc)[:200]}")
            continue
        if res is not None:
            log(f"  {res}")
        store.save_enrichments(cfg)  # 每步都保存，中途被打断也不丢已花额度换来的结果
        budget.save()
    out = store.save_enrichments(cfg)
    budget.save()
    log(f"完成：模型精选 {len(out['triage'])} 条，精读 {len(out['reads'])} 篇，速读卡 {len(out['briefs'])} 张，"
        f"主题研判 {len(out['topic_analyses'])} 个，专题报告 {len(out['research'])} 篇；"
        f"本次约 {budget.run_spent:.2f} 积分，滚动 7 天 {budget.spent_7d():.2f} 积分")
    return 0


def rebuild(log=print) -> None:
    cfg, srcs = settings(), sources()
    store = Store()
    build(store, cfg, srcs, log)
    store.save()
