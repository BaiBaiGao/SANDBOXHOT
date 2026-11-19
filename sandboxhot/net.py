"""最小 HTTP 工具（urllib），带重试与超时。自动遵循系统 HTTP(S)_PROXY。"""
from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; SANDBOXHOT/1.0; RSS reader)"


class HttpError(Exception):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} {url}: {body[:200]}")
        self.status = status
        self.body = body


def request(url: str, *, method: str = "GET", headers: dict | None = None, data: bytes | None = None,
            timeout: float = 30, retries: int = 2, backoff: float = 2.0) -> bytes:
    hdrs = {"User-Agent": UA, "Accept-Encoding": "gzip"}
    hdrs.update(headers or {})
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            last = HttpError(exc.code, body, url)
            # 只有 5xx 和 429 值得重试；4xx 直接抛出
            if exc.code < 500 and exc.code != 429:
                raise last
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last = exc
        if attempt < retries:
            time.sleep(backoff * (2 ** attempt))
    assert last is not None
    raise last


def get_text(url: str, **kw) -> str:
    raw = request(url, **kw)
    for enc in ("utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def get_json(url: str, **kw):
    hdrs = {"Accept": "application/json"}
    hdrs.update(kw.pop("headers", {}) or {})
    return json.loads(get_text(url, headers=hdrs, **kw))


def post_json(url: str, payload: dict, headers: dict | None = None, **kw):
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    hdrs.update(headers or {})
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return json.loads(request(url, method="POST", headers=hdrs, data=body, **kw).decode("utf-8"))
