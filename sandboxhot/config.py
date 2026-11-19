"""配置与本地密钥读取。密钥只从环境变量或本地 .env（已被 git 忽略）读取。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
PROMPTS_DIR = ROOT / "prompts"
DATA_DIR = ROOT / "data"          # 提交到仓库的条目库（不含任何密钥）
STATE_DIR = ROOT / "state"        # 仅本地：额度账本、运行日志（被 git 忽略）
SITE_DIR = ROOT / "docs"          # GitHub Pages 发布目录
SITE_DATA_DIR = SITE_DIR / "data"


def load_dotenv(path: Path | None = None) -> None:
    """读取 KEY=VALUE 格式的 .env，不覆盖已存在的环境变量。"""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise SystemExit(f"JSON 解析失败：{path}：{exc}")


def write_json(path: Path, data, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if compact:
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    else:
        text = json.dumps(data, ensure_ascii=False, indent=1)
    tmp.write_text(text + "\n", encoding="utf-8")
    os.replace(tmp, path)


def settings() -> dict:
    return read_json(CONFIG_DIR / "settings.json", {})


def sources() -> list[dict]:
    return [s for s in read_json(CONFIG_DIR / "sources.json", {"sources": []})["sources"]]


def keywords() -> dict:
    return read_json(CONFIG_DIR / "keywords.json", {})


def topics() -> list[dict]:
    return read_json(CONFIG_DIR / "topics.json", {"topics": []})["topics"]


def topic_list_text() -> str:
    return "\n".join(f"  - {t['slug']}：{t['name']}（{t['definition']}）" for t in topics())


def prompt(name: str, **values: str) -> str:
    """读取提示词，填入共用的 {{style}}（白话写作规则）和 {{topics}}（主题列表），以及调用方给的变量。
    同一份提示词每次填出来的文字完全相同，便于命中服务端缓存。"""
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    if "{{style}}" in text:
        text = text.replace("{{style}}", (PROMPTS_DIR / "style.md").read_text(encoding="utf-8").strip())
    if "{{topics}}" in text:
        text = text.replace("{{topics}}", topic_list_text())
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def api_key() -> str | None:
    load_dotenv()
    key = os.environ.get("TONGJI_API_KEY", "").strip()
    return key or None


def base_url(cfg: dict) -> str:
    load_dotenv()
    return os.environ.get("TONGJI_BASE_URL", cfg.get("api", {}).get("base_url", "")).rstrip("/")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def local_tz(cfg: dict) -> timezone:
    return timezone(timedelta(hours=cfg.get("site", {}).get("timezone_offset_hours", 8)))


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
