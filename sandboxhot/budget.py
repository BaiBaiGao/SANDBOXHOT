"""额度账本：按滚动 7 天统计已消耗积分，所有调用前先检查。账本只存在本地 state/ 目录。"""
from __future__ import annotations

from datetime import timedelta

from .config import STATE_DIR, iso, now_utc, parse_iso, read_json, write_json

LEDGER = STATE_DIR / "usage.json"


class BudgetExceeded(Exception):
    pass


def credits_for(prices: dict, model: str, prompt_tokens: int, cached_tokens: int, completion_tokens: int) -> float:
    p = prices.get(model)
    if not p:
        # 未知模型：按最贵的对话模型保守估计，避免低估
        p = max(prices.values(), key=lambda x: x["output"])
    uncached = max(0, prompt_tokens - cached_tokens)
    return (uncached * p["input"] + cached_tokens * p["cached"] + completion_tokens * p["output"]) / 1_000_000


def estimate_tokens(text: str) -> int:
    """保守估算：中文约 1 字 ≈ 1 token，英文约 4 字符 ≈ 1 token。"""
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    return int(cjk * 1.1 + (len(text) - cjk) / 3.2) + 16


class Budget:
    def __init__(self, cfg: dict, path=LEDGER):
        self.cfg = cfg
        self.b = cfg["budget"]
        self.prices = cfg["prices"]
        self.path = path
        self.data = read_json(path, {"entries": []})
        self.run_spent = 0.0
        self._prune()

    def _prune(self):
        cutoff = now_utc() - timedelta(days=35)
        self.data["entries"] = [e for e in self.data["entries"] if (parse_iso(e["at"]) or cutoff) >= cutoff]

    def spent_since(self, days: float) -> float:
        cutoff = now_utc() - timedelta(days=days)
        return sum(e["credits"] for e in self.data["entries"] if (parse_iso(e["at"]) or cutoff) > cutoff)

    def spent_7d(self) -> float:
        return self.spent_since(7)

    @property
    def weekly_cap(self) -> float:
        return float(self.b["pipeline_weekly_cap"])

    def ratio(self) -> float:
        return self.spent_7d() / self.weekly_cap if self.weekly_cap else 1.0

    def remaining_run(self) -> float:
        return min(self.b["per_run_cap"] - self.run_spent, self.weekly_cap - self.spent_7d())

    def check(self, model: str, est_prompt: int, max_out: int, stop_ratio: float = 1.0) -> float:
        est = credits_for(self.prices, model, est_prompt, 0, max_out)
        if self.spent_7d() + est > self.weekly_cap * stop_ratio:
            raise BudgetExceeded(f"滚动 7 天已用 {self.spent_7d():.2f}/{self.weekly_cap:.0f} 积分（阈值 {stop_ratio:.0%}）")
        if self.run_spent + est > self.b["per_run_cap"]:
            raise BudgetExceeded(f"本次运行已用 {self.run_spent:.2f}/{self.b['per_run_cap']} 积分")
        return est

    def record(self, model: str, purpose: str, usage: dict, fallback_est: float = 0.0) -> float:
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        details = usage.get("prompt_tokens_details") or {}
        cached = int(details.get("cached_tokens") or usage.get("prompt_cache_hit_tokens") or 0)
        credits = credits_for(self.prices, model, prompt, cached, completion) if (prompt or completion) else fallback_est
        reasoning = int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
        self.data["entries"].append({
            "at": iso(now_utc()), "model": model, "purpose": purpose, "prompt": prompt, "cached": cached,
            "completion": completion, "reasoning": reasoning, "credits": round(credits, 5),
        })
        self.run_spent += credits
        return credits

    def save(self):
        write_json(self.path, self.data)

    def report(self) -> str:
        by_model: dict[str, list[float]] = {}
        by_purpose: dict[str, float] = {}
        cutoff = now_utc() - timedelta(days=7)
        calls = 0
        tok_in = tok_cached = tok_out = 0
        for e in self.data["entries"]:
            if (parse_iso(e["at"]) or cutoff) <= cutoff:
                continue
            calls += 1
            by_model.setdefault(e["model"], [0, 0.0])
            by_model[e["model"]][0] += 1
            by_model[e["model"]][1] += e["credits"]
            by_purpose[e["purpose"]] = by_purpose.get(e["purpose"], 0) + e["credits"]
            tok_in += e["prompt"]; tok_cached += e["cached"]; tok_out += e["completion"]
        lines = [
            f"滚动 7 天：{self.spent_7d():.3f} 积分 / 流水线上限 {self.weekly_cap:.0f}（平台周额度 {self.b['weekly_quota']}）",
            f"近 24 小时：{self.spent_since(1):.3f} 积分；调用 {calls} 次；输入 {tok_in} tokens（缓存命中 {tok_cached}），输出 {tok_out} tokens",
        ]
        for m, (n, c) in sorted(by_model.items(), key=lambda x: -x[1][1]):
            lines.append(f"  模型 {m}: {n} 次，{c:.3f} 积分")
        for p, c in sorted(by_purpose.items(), key=lambda x: -x[1]):
            lines.append(f"  用途 {p}: {c:.3f} 积分")
        lines.append("注意：这里是按返回 usage × 单价的本地估算，实际以平台“消费明细”为准（平台只保留 7 天明细）。")
        return "\n".join(lines)
