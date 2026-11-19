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

TRIAGE_FIELDS = ("llm", "model", "triaged", "domain", "score", "relevant", "title_zh", "summary_zh", "tags", "status",
                 "topics", "score1", "score2", "model2", "read_fail", "brief_fail", "applied")
# 只存在 enrichments.json 里、载入时才合并的大字段：云端保存 items.json 时去掉，避免重复存储
OVERLAY_ONLY = ("read", "brief", "related", "story")


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
        for iid, read in (e.get("reads") or {}).items():
            it = self.items.get(iid)
            if it is not None:
                it["read"] = read
                for k in ("title_zh", "summary_zh"):
                    if read.get(k):
                        it[k] = read[k]
                if read.get("topics"):
                    it["topics"] = read["topics"]
                if "applied" in read:
                    it["applied"] = read["applied"]
        for iid, brief in (e.get("briefs") or {}).items():
            if iid in self.items:
                self.items[iid]["brief"] = brief
        for iid, rel in (e.get("related") or {}).items():
            if iid in self.items:
                self.items[iid]["related"] = rel
        for iid, n in (e.get("attempts") or {}).items():
            if iid in self.items and not self.items[iid].get("llm"):
                self.items[iid]["attempts"] = max(n, self.items[iid].get("attempts", 0))
        for kind in ("daily", "weekly"):
            lst = self.digests.setdefault(kind, [])
            for d in (e.get("digests") or {}).get(kind, []):
                lst[:] = [x for x in lst if x["key"] != d["key"]]
                lst.append(d)
        self.stories: dict = e.get("stories") or {}
        self.dupes: list = e.get("dupes") or []
        self.topic_analyses: dict = e.get("topic_analyses") or {}
        self.research: list = e.get("research") or []

    def save_enrichments(self, cfg: dict) -> dict:
        """只导出模型产生的结果，写入 data/enrichments.json。"""
        r = cfg["retention"]
        out = {"triage": {}, "reads": {}, "briefs": {}, "related": {}, "attempts": {},
               "digests": {"daily": [], "weekly": []}}
        for iid, it in sorted(self.items.items()):
            if it.get("llm"):
                out["triage"][iid] = {k: it[k] for k in TRIAGE_FIELDS if k in it}
                if it.get("brief"):
                    out["briefs"][iid] = it["brief"]
                if it.get("read"):
                    out["reads"][iid] = it["read"]
            elif it.get("attempts"):
                out["attempts"][iid] = it["attempts"]
            if it.get("related"):
                out["related"][iid] = it["related"]
        for kind, keep in (("daily", r["daily_digests_keep"]), ("weekly", r["weekly_digests_keep"])):
            ai = [d for d in self.digests.get(kind, []) if d.get("ai")]
            out["digests"][kind] = sorted(ai, key=lambda d: d["key"], reverse=True)[:keep]
        out["stories"] = {k: v for k, v in sorted(self.stories.items()) if k in self.items}
        out["dupes"] = [p for p in self.dupes if p[0] in self.items and p[1] in self.items]
        out["topic_analyses"] = self.topic_analyses
        out["research"] = sorted(self.research, key=lambda d: d["created"], reverse=True)[:60]
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
        slim = {iid: {k: v for k, v in it.items() if k not in OVERLAY_ONLY} for iid, it in sorted(self.items.items())}
        write_json(ITEMS, {"items": slim})
        write_json(SEEN, {"seen": dict(sorted(self.seen.items()))}, compact=True)
        write_json(DIGESTS, self.digests)
        write_json(RUNTIME, self.runtime)
