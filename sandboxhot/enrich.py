"""大模型加工：批量精选、双评复核、中文精读、速读卡、embedding 相关推荐、事件综述。

所有任务都按 budget.allow(tier) 匀速花费：新条目用 normal，历史回填用 backfill。"""
from __future__ import annotations

import json
import math
import operator
import re
from datetime import timedelta

from . import cluster
from .budget import BudgetExceeded
from .config import STATE_DIR, iso, now_utc, parse_iso, prompt, read_json, topics, write_json
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
        "topics": valid_topics(res.get("topics")),
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


URL_RE = re.compile(r"https?://[^\s)\]}>,;\"'<]+")
VALIDATION = ("real_data", "human_experiment", "benchmark", "none", "unclear")
RESOURCE_TYPES = ("code", "data", "benchmark", "model", "demo", "project")


def valid_topics(values) -> list[str]:
    slugs = {t["slug"] for t in topics()}
    out = []
    for v in values or []:
        v = str(v).strip()
        if v in slugs and v not in out:
            out.append(v)
    return out[:3]


def is_new(it: dict, cfg: dict) -> bool:
    """新条目（近几天加入且不是历史回填）走 normal 档；其余走 backfill 档，只在额度有富余时处理。"""
    if it.get("backfill"):
        return False
    added = parse_iso(it.get("added"))
    return bool(added and now_utc() - added <= timedelta(days=cfg["pipeline"]["new_item_days"]))


def _queue(cands: list[dict], cfg: dict, phase: str) -> list[dict]:
    cands = [it for it in cands if is_new(it, cfg) == (phase == "new")]
    cands.sort(key=lambda it: (it.get("score", 0), it.get("published", "")), reverse=True)
    return cands


def links_in(it: dict) -> list[str]:
    found = []
    for u in URL_RE.findall(it.get("text", "")):
        u = u.rstrip(".")
        if u not in found:
            found.append(u)
    if it.get("kind") == "repo":
        found.insert(0, it["url"])
    pdf = (it.get("extra") or {}).get("pdf")
    if pdf and pdf not in found:
        found.append(pdf)
    return found[:12]


def _per_item(store, cfg, llm: LLM, log, *, name: str, role: str, cands: list[dict], tier: str, limit: int,
              build_user, max_tokens: int, handle, stop_ratio: float = 1.0) -> int:
    done = 0
    for it in cands[:limit]:
        if not llm.available or not llm.budget.allow(tier):
            if cands:
                log(f"  · {name}：额度进度 {llm.budget.pace():.0%}，{tier} 档暂停，剩余留到下次")
            break
        try:
            text, model = llm.chat(role, prompt(role), build_user(it), max_tokens=max_tokens, purpose=name,
                                   stop_ratio=stop_ratio)
        except (BudgetExceeded, LLMUnavailable) as exc:
            log(f"  ! {name}停止：{exc}")
            break
        if handle(it, text, model):
            done += 1
        else:  # 输出无法解析：记一次失败，失败 2 次后不再重试，避免反复花额度
            key = f"{role}_fail"
            it[key] = it.get(key, 0) + 1
    return done


def run_reads(store, cfg: dict, llm: LLM, log=print, phase: str = "new") -> int:
    """中文精读：标题、摘要、中文全文梳理、为什么值得看、主题、资源链接、验证强度。"""
    p = cfg["pipeline"]
    cands = _queue([it for it in store.items.values()
                    if it.get("status") == "selected" and it.get("llm") and not it.get("read")
                    and it.get("read_fail", 0) < 2], cfg, phase)

    def user(it):
        return json.dumps({"source": it["source_name"], "kind": it["kind"], "venue": (it.get("extra") or {}).get("venue", ""),
                           "published": it["published"][:10], "authors": it.get("authors", [])[:6], "title": it["title"],
                           "text": it.get("text", "")[: p["read_text_chars"]], "links": links_in(it)}, ensure_ascii=False)

    def handle(it, text, model):
        data = parse_json_block(text)
        if not isinstance(data, dict):
            return False
        allowed = set(links_in(it))
        res = []
        for r in data.get("resources") or []:
            if isinstance(r, dict) and r.get("url") in allowed and r.get("type") in RESOURCE_TYPES:
                res.append({"type": r["type"], "name": str(r.get("name") or r["url"])[:80], "url": r["url"]})
        read = {
            "title_zh": str(data.get("title_zh") or it.get("title_zh") or "")[:120],
            "summary_zh": str(data.get("summary_zh") or it.get("summary_zh") or "")[:400],
            "abstract_zh": str(data.get("abstract_zh") or "")[:1600],
            "why": str(data.get("why") or "")[:240],
            "topics": valid_topics(data.get("topics")) or it.get("topics", []),
            "resources": res[:8],
            "validation": data.get("validation") if data.get("validation") in VALIDATION else "unclear",
            "model": model, "at": iso(now_utc()),
        }
        it["read"] = read
        it["title_zh"], it["summary_zh"], it["topics"] = read["title_zh"], read["summary_zh"], read["topics"]
        return True

    tier = "normal" if phase == "new" else "backfill"
    return _per_item(store, cfg, llm, log, name=f"精读-{phase}", role="read", cands=cands, tier=tier,
                     limit=p["max_reads_per_run"], build_user=user, max_tokens=1800, handle=handle)


def run_briefs(store, cfg: dict, llm: LLM, log=print, phase: str = "new") -> int:
    p = cfg["pipeline"]
    if llm.budget.ratio() >= cfg["budget"]["brief_stop_ratio"]:
        log(f"  · 本周额度已用 {llm.budget.ratio():.0%}，跳过速读卡以节省额度")
        return 0
    cands = _queue([it for it in store.items.values()
                    if it.get("status") == "selected" and it.get("llm") and not it.get("brief")
                    and it.get("brief_fail", 0) < 2
                    and it.get("domain") in p["brief_domains"] and it.get("score", 0) >= p["brief_min_score"]
                    and len(it.get("text", "")) >= 200], cfg, phase)

    def user(it):
        return json.dumps({"source": it["source_name"], "title": it["title"], "venue": (it.get("extra") or {}).get("venue", ""),
                           "text": it.get("text", "")[:3500]}, ensure_ascii=False)

    def handle(it, text, model):
        data = parse_json_block(text)
        if not isinstance(data, dict):
            return False
        keys = ("question", "setup", "method", "findings", "validation", "limits", "reuse")
        it["brief"] = {k: str(data.get(k, "未说明"))[:360] for k in keys}
        return True

    tier = "normal" if phase == "new" else "backfill"
    return _per_item(store, cfg, llm, log, name=f"速读卡-{phase}", role="brief", cands=cands, tier=tier,
                     limit=p["max_briefs_per_run"], build_user=user, max_tokens=1400, handle=handle,
                     stop_ratio=cfg["budget"]["brief_stop_ratio"])


def run_second(store, cfg: dict, llm: LLM, log=print) -> dict:
    """双评：分数落在边界区间的条目，换一个模型独立再评一次；两次分歧大时取更谨慎的结果。"""
    p = cfg["pipeline"]
    lo, hi = p["second_score_range"]
    stats = {"sent": 0, "changed": 0}
    cands = [it for it in store.items.values()
             if it.get("llm") and "score2" not in it and lo <= it.get("score", 0) <= hi]
    cands.sort(key=lambda it: (is_new(it, cfg), it.get("score", 0)), reverse=True)
    cands = cands[: p["max_second_per_run"]]
    if not cands or not llm.available or not llm.budget.allow("normal"):
        return stats
    system = prompt("second")
    th = p["select_threshold"]
    for start in range(0, len(cands), p["triage_batch_size"]):
        batch = cands[start:start + p["triage_batch_size"]]
        user = "请独立评估以下材料：\n" + json.dumps([_material(i, it, p["triage_text_chars"]) for i, it in enumerate(batch)],
                                                   ensure_ascii=False)
        try:
            text, model = llm.chat("second", system, user, max_tokens=60 * len(batch) + 80, purpose="second")
        except (BudgetExceeded, LLMUnavailable) as exc:
            log(f"  ! 双评停止：{exc}")
            break
        data = parse_json_block(text) or {}
        results = {r.get("i"): r for r in data.get("items", []) if isinstance(r, dict)}
        for i, it in enumerate(batch):
            r = results.get(i)
            if r is None:
                continue
            try:
                s2 = max(0, min(100, int(r.get("score", 0))))
            except (TypeError, ValueError):
                continue
            s1 = it.get("score", 0)
            agree = abs(s1 - s2) <= p["second_disagree"] and bool(r.get("relevant")) == bool(it.get("relevant"))
            final = round((s1 + s2) / 2) if agree else min(s1, s2)
            relevant = bool(it.get("relevant")) and (bool(r.get("relevant")) or agree)
            before = it.get("status")
            it.update({"score1": s1, "score2": s2, "model2": model, "score": final, "relevant": relevant})
            it["status"] = "selected" if relevant and final >= th.get(it.get("domain"), 55) else "filtered"
            stats["sent"] += 1
            stats["changed"] += int(before != it["status"])
    return stats


EMBED_CACHE = STATE_DIR / "embeddings.json"


def _norm(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def run_embeddings(store, cfg: dict, llm: LLM, log=print) -> dict:
    """给入选条目算 embedding（本地缓存，不提交），据此生成“相关推荐”和跨来源的同事件配对。"""
    p = cfg["pipeline"]
    cache: dict = read_json(EMBED_CACHE, {})
    selected = [it for it in store.items.values() if it.get("status") == "selected"]
    todo = [it for it in selected if it["id"] not in cache]
    new = 0
    if todo and llm.available and llm.budget.allow("normal"):
        for start in range(0, len(todo), p["embed_batch"]):
            batch = todo[start:start + p["embed_batch"]]
            texts = [f"{it['title']}\n{it.get('title_zh', '')}\n{(it.get('summary_zh') or it.get('text', ''))[:500]}" for it in batch]
            try:
                vecs = llm.embed(texts, dimensions=p["embed_dimensions"])
            except (BudgetExceeded, LLMUnavailable) as exc:
                log(f"  ! embedding 停止：{exc}")
                break
            for it, v in zip(batch, vecs):
                if v:
                    cache[it["id"]] = [round(x, 5) for x in _norm(v)]
                    new += 1
        write_json(EMBED_CACHE, {k: v for k, v in cache.items() if k in store.items}, compact=True)
    vecs = {it["id"]: cache[it["id"]] for it in selected if it["id"] in cache}
    ids = list(vecs)
    sims: dict[str, list[tuple[float, str]]] = {i: [] for i in ids}
    dupes = []
    recent = {it["id"] for it in selected if (parse_iso(it.get("added")) or now_utc()) > now_utc() - timedelta(days=14)}
    for a_i, a in enumerate(ids):
        va = vecs[a]
        for b in ids[a_i + 1:]:
            sim = sum(map(operator.mul, va, vecs[b]))
            if sim >= p["related_min_sim"]:
                sims[a].append((sim, b))
                sims[b].append((sim, a))
                ia, ib = store.items[a], store.items[b]
                # 同一事件：只合并新闻/帖子类（两篇不同论文永远是两件事），且来源不同、标题也有重合
                if sim >= p["dupe_sim"] and a in recent and b in recent and "paper" not in (ia["kind"], ib["kind"]) \
                        and ia["source_id"] != ib["source_id"] \
                        and cluster.jaccard(cluster.tokens(ia), cluster.tokens(ib)) >= 0.2:
                    dupes.append(sorted([a, b]))
    for i in ids:
        top = sorted(sims[i], reverse=True)[: p["related_top"]]
        store.items[i]["related"] = [b for _, b in top]
    store.dupes = dupes
    return {"embedded": new, "with_related": sum(1 for i in ids if store.items[i]["related"]), "dupes": len(dupes)}


def run_stories(store, cfg: dict, llm: LLM, log=print) -> int:
    """事件综述：同一事件有 ≥2 个独立来源时，合写一段。成员没变就不重写。"""
    groups: dict[str, list[dict]] = {}
    for it in store.items.values():
        if it.get("status") == "selected" and it.get("cluster_size", 1) > 1:
            groups.setdefault(it["cluster"], []).append(it)
    done = 0
    for lead, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if done >= cfg["pipeline"]["max_stories_per_run"]:
            break
        key_members = sorted(m["id"] for m in members)
        old = store.stories.get(lead)
        if old and old.get("members") == key_members:
            continue
        if not llm.available or not llm.budget.allow("normal"):
            break
        material = [{"source": m["source_name"], "title": m.get("title_zh") or m["title"], "published": m["published"][:10],
                     "text": (m.get("summary_zh") or m.get("text", ""))[:800], "url": m["url"]} for m in members[:8]]
        try:
            text, model = llm.chat("story", prompt("story"), json.dumps(material, ensure_ascii=False),
                                   max_tokens=1000, purpose="story")
        except (BudgetExceeded, LLMUnavailable) as exc:
            log(f"  ! 事件综述停止：{exc}")
            break
        if text.strip():
            store.stories[lead] = {"text": text.strip()[:800], "members": key_members, "model": model, "at": iso(now_utc())}
            done += 1
    return done


def ensure_domain_guess(it: dict, kw: dict) -> None:
    if "domain_guess" not in it:
        it["domain_guess"] = guess_domain(it, kw)
