#!/usr/bin/env python3
"""云端加工的节流闸门（GitHub Actions 每小时触发一次，GitHub 经常跳过定时任务，所以多触发、靠这里节流）。

  python scripts/cloud_gate.py check   输出 run=true|false 和原因（写进 $GITHUB_OUTPUT）
  python scripts/cloud_gate.py record success|failure|skipped   记录本次结果到 data/cloud-schedule.json

规则：
- 手动运行（workflow_dispatch）总是执行。
- 上一次成功加工距今不满 MIN_HOURS（默认 3.75 小时，配合每小时第 23 分触发，节奏约 4 小时）就跳过。
- 上一次尝试失败（比如 VPN 登录失败）时，距那次尝试也要满 MIN_HOURS 才重试，避免每小时登录失败一次把账号锁住。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(__file__).resolve().parent.parent / "data" / "cloud-schedule.json"


def _parse(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def decide(state: dict, now: datetime, event: str, min_hours: float) -> tuple[bool, str]:
    if event == "workflow_dispatch":
        return True, "手动运行，直接执行"
    last_ok = _parse(state.get("last_success"))
    last_try = _parse(state.get("last_attempt"))
    if last_ok and (now - last_ok).total_seconds() < min_hours * 3600:
        return False, f"上次成功加工在 {(now - last_ok).total_seconds() / 3600:.1f} 小时前，不满 {min_hours} 小时"
    if state.get("last_result") == "failure" and last_try and (now - last_try).total_seconds() < min_hours * 3600:
        return False, f"上次尝试失败在 {(now - last_try).total_seconds() / 3600:.1f} 小时前，等满 {min_hours} 小时再试，避免账号被锁"
    return True, "距上次成功加工已满间隔，执行"


def load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def record(result: str, now: datetime) -> dict:
    state = load()
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    state["last_attempt"] = stamp
    state["last_result"] = result
    if result == "success":
        state["last_success"] = stamp
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return state


def main() -> int:
    now = datetime.now(timezone.utc)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        run, why = decide(load(), now, os.environ.get("GITHUB_EVENT_NAME", ""), float(os.environ.get("MIN_HOURS", "3.75")))
        print(("执行：" if run else "跳过：") + why)
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a", encoding="utf-8") as f:
                f.write(f"run={'true' if run else 'false'}\n")
        return 0
    if cmd == "record":
        print(record(sys.argv[2], now))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
