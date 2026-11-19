"""条目库：data/ 下的 JSON 文件（提交到仓库），以及 state/ 下的本地运行状态。"""
from __future__ import annotations

from datetime import timedelta

from .config import DATA_DIR, STATE_DIR, now_utc, parse_iso, read_json, write_json

ITEMS = DATA_DIR / "items.json"
SEEN = DATA_DIR / "seen.json"
DIGESTS = DATA_DIR / "digests.json"
RUNTIME = STATE_DIR / "runtime.json"
# 笔记本（校园网/VPN 内）用同济 API 生成的结果单独存放：云端 Actions 只读不写，笔记本只写这一个文件，互不冲突
ENRICH = DATA_DIR / "enrichments.json"

TRIAGE_FIELDS = ("llm", "model", "triaged", "domain", "score", "relevant", "title_zh", "summary_zh", "tags", "status")


class Store:
    def __init__(self):
        self.items: dict[str, dict] = read_json(ITEMS, {"items": {}})["items"]
        self.seen: dict[str, str] = read_json(SEEN, {"seen": {}})["seen"]
        self.digests: dict = read_json(DIGESTS, {"daily": [], "weekly": []})
        self.runtime: dict = read_json(RUNTIME, {})
        self.enrich: dict = read_json(ENRICH, {})
        self._overlay()

    def _overlay(self) -> None:
        """把 enrichments.json 中的模型结果合并到条目和日报上（模型结果优先于规则结果）。"""
        e = self.enrich
        for iid, fields in (e.get("triage") or {}).items():
            if iid in self.items:
                self.items[iid].update({k: fields[k] for k in TRIAGE_FIELDS if k in fields})
        for iid, brief in (e.get("briefs") or {}).items():
            if iid in self.items:
                self.items[iid]["brief"] = brief
        for iid, n in (e.get("attempts") or {}).items():
            if iid in self.items and not self.items[iid].get("llm"):
                self.items[iid]["attempts"] = max(n, self.items[iid].get("attempts", 0))
        for kind in ("daily", "weekly"):
            lst = self.digests.setdefault(kind, [])
            for d in (e.get("digests") or {}).get(kind, []):
                lst[:] = [x for x in lst if x["key"] != d["key"]]
                lst.append(d)

    def save_enrichments(self, cfg: dict) -> dict:
        """只导出模型产生的结果，写入 data/enrichments.json。"""
        r = cfg["retention"]
        out = {"triage": {}, "briefs": {}, "attempts": {}, "digests": {"daily": [], "weekly": []}}
        for iid, it in sorted(self.items.items()):
            if it.get("llm"):
                out["triage"][iid] = {k: it[k] for k in TRIAGE_FIELDS if k in it}
                if it.get("brief"):
                    out["briefs"][iid] = it["brief"]
            elif it.get("attempts"):
                out["attempts"][iid] = it["attempts"]
        for kind, keep in (("daily", r["daily_digests_keep"]), ("weekly", r["weekly_digests_keep"])):
            ai = [d for d in self.digests.get(kind, []) if d.get("ai")]
            out["digests"][kind] = sorted(ai, key=lambda d: d["key"], reverse=True)[:keep]
        write_json(ENRICH, out)
        return out

    def known(self, item_id: str) -> bool:
        return item_id in self.items or item_id in self.seen

    def prune(self, cfg: dict) -> int:
        r = cfg["retention"]
        now = now_utc()
        removed = 0
        for iid in list(self.items):
            it = self.items[iid]
            added = parse_iso(it.get("added")) or now
            keep_days = r["selected_days"] if it.get("status") == "selected" else r["filtered_days"]
            if now - added > timedelta(days=keep_days):
                # 移出主库，但记入 seen，防止被重新抓到后再次消耗额度
                self.seen[iid] = it.get("added", "")
                del self.items[iid]
                removed += 1
        cutoff = now - timedelta(days=r["seen_days"])
        for iid in list(self.seen):
            if (parse_iso(self.seen[iid]) or cutoff) < cutoff and iid not in self.items:
                del self.seen[iid]
        self.digests["daily"] = sorted(self.digests.get("daily", []), key=lambda d: d["key"], reverse=True)[: r["daily_digests_keep"]]
        self.digests["weekly"] = sorted(self.digests.get("weekly", []), key=lambda d: d["key"], reverse=True)[: r["weekly_digests_keep"]]
        return removed

    def save(self):
        write_json(ITEMS, {"items": dict(sorted(self.items.items()))})
        write_json(SEEN, {"seen": dict(sorted(self.seen.items()))}, compact=True)
        write_json(DIGESTS, self.digests)
        write_json(RUNTIME, self.runtime)
