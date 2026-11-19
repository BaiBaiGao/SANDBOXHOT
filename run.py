#!/usr/bin/env python3
"""SANDBOXHOT 命令行。

  python run.py update            采集 + 精选 + 生成站点（日常就跑这个）
  python run.py update --no-llm   完全不调用模型（零额度，纯规则）
  python run.py enrich            笔记本模式：只用同济 API 给云端条目补模型精选（不采集）
  python run.py build             只用已有数据重新生成站点
  python run.py budget            查看本地额度账本
  python run.py check             检查密钥与授权模型列表（GET /v1/models，不消耗积分）
  python run.py guard             提交前检查仓库里有没有误放的 API Key
  python run.py serve             本地预览网站 http://localhost:8000
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台中文
    except Exception:  # noqa: BLE001
        pass

from sandboxhot import pipeline  # noqa: E402
from sandboxhot.budget import Budget  # noqa: E402
from sandboxhot.config import ROOT, SITE_DIR, api_key, settings  # noqa: E402
from sandboxhot.llm import LLM  # noqa: E402

SECRET_RE = re.compile(r"sk-[A-Za-z0-9]{20,}")


def cmd_check(_args) -> int:
    cfg = settings()
    key = api_key()
    if not key:
        print("未找到 TONGJI_API_KEY。运行 scripts\\set_key.ps1，或在仓库根目录创建 .env。")
        return 1
    print(f"已读取本地密钥：{key[:5]}…{key[-4:]}（长度 {len(key)}）")
    llm = LLM(cfg, Budget(cfg))
    try:
        ids = llm.list_models()
    except Exception as exc:  # noqa: BLE001
        print(f"调用 /v1/models 失败：{exc}\n校外请先连学校 VPN；可运行 nslookup agi.tongji.edu.cn 检查解析。")
        return 1
    print(f"该 Key 授权的模型（{len(ids)} 个）：" + ", ".join(ids))
    wanted = {m for role in cfg["models"].values() for m in role}
    missing = sorted(wanted - set(ids))
    if missing:
        print("注意：settings.json 中这些模型不在授权列表里，会被自动跳过：" + ", ".join(missing))
    else:
        print("settings.json 配置的模型全部可用。")
    return 0


def cmd_guard(_args) -> int:
    try:
        files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.split()
    except Exception as exc:  # noqa: BLE001
        print(f"git 不可用：{exc}")
        return 1
    bad = []
    for f in files:
        p = ROOT / f
        if not p.is_file() or p.stat().st_size > 5_000_000:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if SECRET_RE.search(text):
            bad.append(f)
    if bad:
        print("发现疑似 API Key，已阻止提交：" + ", ".join(bad))
        return 2
    print("密钥检查通过：将要提交的文件里没有 API Key。")
    return 0


def cmd_serve(args) -> int:
    import functools
    import http.server
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE_DIR))
    print(f"本地预览：http://localhost:{args.port}  （Ctrl+C 退出）")
    http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="SANDBOXHOT")
    sub = ap.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("update")
    up.add_argument("--no-llm", action="store_true", help="不调用模型")
    up.add_argument("--force", action="store_true", help="忽略抓取间隔，所有信源立即抓取")
    up.add_argument("--no-fetch", action="store_true", help="不抓取，只处理已有候选")
    up.add_argument("--require-content", action="store_true", help="采集全部失败或无内容时退出")
    sub.add_parser("enrich")
    sub.add_parser("build")
    sub.add_parser("budget")
    sub.add_parser("check")
    sub.add_parser("guard")
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    if args.cmd == "update":
        pipeline.update(use_llm=not args.no_llm, force_fetch=args.force, fetch=not args.no_fetch,
                        require_content=args.require_content)
        return 0
    if args.cmd == "enrich":
        return pipeline.enrich_only()
    if args.cmd == "build":
        pipeline.rebuild()
        return 0
    if args.cmd == "budget":
        print(Budget(settings()).report())
        return 0
    return {"check": cmd_check, "guard": cmd_guard, "serve": cmd_serve}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
