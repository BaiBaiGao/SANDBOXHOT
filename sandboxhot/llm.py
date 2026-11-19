"""同济平台 OpenAI 兼容接口客户端（POST /v1/chat/completions），内置额度检查与模型回退。"""
from __future__ import annotations

import json
import re
import time

from . import net
from .budget import Budget, BudgetExceeded, estimate_tokens
from .config import api_key, base_url


class LLMUnavailable(Exception):
    """密钥缺失、鉴权失败、网络不可达（不在校园网/VPN）或额度/限流：本次运行停止调用模型。"""


class LLM:
    def __init__(self, cfg: dict, budget: Budget, *, enabled: bool = True, log=print):
        self.cfg = cfg
        self.budget = budget
        self.key = api_key() if enabled else None
        self.base = base_url(cfg)
        self.timeout = cfg.get("api", {}).get("timeout_seconds", 120)
        self.log = log
        self.disabled_reason = None if self.key else ("已用 --no-llm 关闭" if not enabled else "未找到 TONGJI_API_KEY（.env 或环境变量）")
        self.bad_models: set[str] = set()

    @property
    def available(self) -> bool:
        return self.disabled_reason is None

    def disable(self, reason: str):
        if self.disabled_reason is None:
            self.disabled_reason = reason
            self.log(f"  ! 停止调用模型：{reason}")

    def list_models(self) -> list[str]:
        if not self.key:
            raise LLMUnavailable(self.disabled_reason or "无密钥")
        data = net.get_json(f"{self.base}/models", headers={"Authorization": f"Bearer {self.key}"},
                            timeout=30, retries=1)
        return [m.get("id") for m in data.get("data", [])]

    def chat(self, role: str, system: str, user: str, *, max_tokens: int, purpose: str,
             stop_ratio: float = 1.0, temperature: float = 0.2, timeout: float | None = None) -> tuple[str, str]:
        """依次尝试 settings.models[role] 中的模型。返回 (文本, 实际模型)。"""
        if not self.available:
            raise LLMUnavailable(self.disabled_reason)
        models = [m for m in self.cfg["models"][role] if m not in self.bad_models]
        if not models:
            raise LLMUnavailable(f"{role} 没有可用模型")
        est_prompt = estimate_tokens(system) + estimate_tokens(user)
        last_err = None
        for model in models:
            est = self.budget.check(model, est_prompt, max_tokens, stop_ratio)  # 超额直接抛 BudgetExceeded
            payload = {
                "model": model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False,
            }
            effort = self.cfg.get("reasoning", {}).get(model)
            if effort:
                payload["reasoning_effort"] = effort
            for attempt in range(3):
                try:
                    resp = net.post_json(f"{self.base}/chat/completions", payload,
                                         headers={"Authorization": f"Bearer {self.key}"},
                                         timeout=timeout or self.timeout, retries=0)
                except net.HttpError as exc:
                    if exc.status in (401,):
                        self.disable("API Key 无效、停用或缺少 Bearer（401）")
                        raise LLMUnavailable(self.disabled_reason)
                    if exc.status == 403:
                        self.disable("403：不在校园网/学校 VPN，或模型未授权")
                        raise LLMUnavailable(self.disabled_reason)
                    if exc.status == 429:
                        self.disable("429：额度或并发限制，本次停止，下次运行再试")
                        raise LLMUnavailable(self.disabled_reason)
                    if exc.status in (400, 404):
                        # 模型名不对/未授权/参数不被支持：换下一个模型
                        self.log(f"  ! {model} 返回 {exc.status}，改用下一个模型：{exc.body[:120]}")
                        self.bad_models.add(model)
                        last_err = exc
                        break
                    last_err = exc  # 5xx：退避重试
                except (OSError, TimeoutError) as exc:
                    last_err = exc
                    if attempt == 0 and "timed out" not in str(exc).lower():
                        # 连不上：大概率不在校园网/VPN，不再空耗时间
                        self.disable(f"连不上 {self.base}（校外请先连学校 VPN）：{str(exc)[:80]}")
                        raise LLMUnavailable(self.disabled_reason)
                else:
                    usage = resp.get("usage") or {}
                    choice = (resp.get("choices") or [{}])[0]
                    text = ((choice.get("message") or {}).get("content")) or ""
                    spent = self.budget.record(model, purpose, usage, fallback_est=est)
                    if not usage:
                        self.log("  ! 响应没有 usage，额度按 0 记录，请到平台消费明细核对")
                    if choice.get("finish_reason") == "length":
                        self.log(f"  ! {model} 输出被 max_tokens 截断（{purpose}）")
                    self.log(f"    {model} · {purpose} · {usage.get('prompt_tokens', '?')}→{usage.get('completion_tokens', '?')} tokens · {spent:.4f} 积分")
                    return text, model
                time.sleep(3 * (attempt + 1))
        raise LLMUnavailable(f"所有 {role} 模型都失败：{last_err}")

    def embed(self, texts: list[str], *, purpose: str = "embed", dimensions: int = 256) -> list[list[float]]:
        """POST /v1/embeddings（Qwen3-Embedding，0.5 积分/百万 tokens）。"""
        if not self.available:
            raise LLMUnavailable(self.disabled_reason)
        model = self.cfg["models"]["embed"][0]
        est_prompt = sum(estimate_tokens(t) for t in texts)
        est = self.budget.check(model, est_prompt, 0)
        payload = {"model": model, "input": texts, "dimensions": dimensions}
        try:
            resp = net.post_json(f"{self.base}/embeddings", payload, headers={"Authorization": f"Bearer {self.key}"},
                                 timeout=self.timeout, retries=1)
        except net.HttpError as exc:
            if exc.status in (401, 403, 429):
                self.disable(f"embeddings 返回 {exc.status}")
            raise LLMUnavailable(f"embeddings 失败：{exc}")
        except OSError as exc:
            raise LLMUnavailable(f"embeddings 失败：{exc}")
        usage = resp.get("usage") or {}
        self.budget.record(model, purpose, usage, fallback_est=est)
        rows = sorted(resp.get("data") or [], key=lambda r: r.get("index", 0))
        return [r.get("embedding") or [] for r in rows]


def tidy(text: str) -> str:
    """写作规则的机械兜底：去掉破折号（—、——），保留数字范围里的连接号 –。"""
    if not text:
        return text
    text = re.sub(r"\s*—+\s*", "，", text)
    text = re.sub(r"，{2,}", "，", text)
    text = re.sub(r"，([。！？；）」”])", r"\1", text)
    return text


def parse_json_block(text: str):
    """从模型输出中取出第一个 JSON 对象（容忍 ```json 包裹和前后多余文字）。"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


__all__ = ["LLM", "LLMUnavailable", "BudgetExceeded", "parse_json_block", "tidy"]
