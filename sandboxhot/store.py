"""条目库：data/ 下的 JSON 文件（提交到仓库），以及 state/ 下的本地运行状态。"""
from __future__ import annotations

from datetime import timedelta

from .config import DATA_DIR, STATE_DIR, now_utc, parse_iso, read_json, write_json

ITEMS = DATA_DIR / "items.json"
SEEN = DATA_DIR / "seen.json"
DIGESTS = DATA_DIR / "digests.json"
RUNTIME = STATE_DIR / "runtime.json"


class Store:
    def __init__(self):
        self.items: dict[str, dict] = read_json(ITEMS, {"items": {}})["items"]
        self.seen: dict[str, str] = read_json(SEEN, {"seen": {}})["seen"]
        self.digests: dict = read_json(DIGESTS, {"daily": [], "weekly": []})
        self.runtime: dict = read_json(RUNTIME, {})

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
