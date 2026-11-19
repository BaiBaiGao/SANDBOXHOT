"""采集：RSS/Atom、arXiv、OpenAlex、Hacker News、GitHub。全部免费接口，不消耗积分。"""
from __future__ import annotations

import hashlib
import html
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from . import net
from .config import iso, now_utc

TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|ref_src|source$)")
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean_text(value: str | None, limit: int = 4000) -> str:
    if not value:
        return ""
    text = html.unescape(TAG_RE.sub(" ", value))
    text = WS_RE.sub(" ", text).strip()
    return text[:limit]


def canonical_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    parts = urllib.parse.urlsplit(url)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True) if not TRACKING.match(k)]
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path
    if host.endswith("arxiv.org"):
        host = "arxiv.org"
        m = re.search(r"/(?:abs|pdf)/([^/?#]+?)(?:v\d+)?(?:\.pdf)?$", path)
        if m:
            path = f"/abs/{m.group(1)}"
    path = path.rstrip("/") or "/"
    return urllib.parse.urlunsplit(("https", host, path, urllib.parse.urlencode(query), ""))


def item_id(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode("utf-8")).hexdigest()[:16]


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            m = re.match(r"(\d{4}-\d{2}-\d{2})", value)
            if not m:
                return None
            dt = datetime.fromisoformat(m.group(1))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def make_item(source: dict, *, url: str, title: str, summary: str = "", published: datetime | None = None,
              authors: list[str] | None = None, extra: dict | None = None, kind: str | None = None) -> dict | None:
    url = canonical_url(url)
    title = clean_text(title, 400)
    if not url or not title:
        return None
    return {
        "id": item_id(url),
        "url": url,
        "title": title,
        "text": clean_text(summary),
        "source_id": source["id"],
        "source_name": source["name"],
        "source_group": source.get("group", ""),
        "kind": kind or ("paper" if source["kind"] in ("arxiv", "openalex") else source["kind"]),
        "tier": source.get("tier", "T2"),
        "focused": bool(source.get("focused")),
        "published": iso(published) if published else iso(now_utc()),
        "authors": authors or [],
        "extra": extra or {},
    }


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child(el, name: str):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _children(el, name: str):
    return [c for c in el if _local(c.tag) == name]


def _text(el) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def parse_feed(xml_text: str, source: dict) -> list[dict]:
    """解析 RSS 2.0 / Atom / RDF。"""
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    entries = [e for e in root.iter() if _local(e.tag) in ("item", "entry")]
    items = []
    for e in entries:
        title = _text(_child(e, "title"))
        link = ""
        link_el = None
        for l in _children(e, "link"):
            rel = l.get("rel", "alternate")
            if l.get("href") and rel == "alternate":
                link_el = l
                break
        if link_el is not None:
            link = link_el.get("href", "")
        else:
            l = _child(e, "link")
            link = (l.get("href") if l is not None and l.get("href") else _text(l))
        if not link:
            guid = _child(e, "guid")
            if guid is not None and _text(guid).startswith("http"):
                link = _text(guid)
        summary = ""
        for name in ("description", "summary", "encoded", "content"):
            c = _child(e, name)
            if c is not None and _text(c):
                summary = _text(c)
                break
        date = None
        for name in ("pubdate", "published", "updated", "date", "issued"):
            c = _child(e, name)
            if c is not None and _text(c):
                date = parse_date(_text(c))
                if date:
                    break
        authors = []
        for a in _children(e, "author") + _children(e, "creator"):
            n = _child(a, "name")
            name = _text(n) if n is not None else _text(a)
            if name:
                authors.append(clean_text(name, 80))
        it = make_item(source, url=link, title=title, summary=summary, published=date, authors=authors[:8])
        if it:
            items.append(it)
    return items


def fetch_rss(source: dict) -> list[dict]:
    return parse_feed(net.get_text(source["url"], timeout=25, retries=1), source)


ARXIV_API = "https://export.arxiv.org/api/query"


def parse_arxiv(xml_text: str, source: dict) -> list[dict]:
    root = ET.fromstring(xml_text.encode("utf-8"))
    out = []
    for e in root:
        if _local(e.tag) != "entry":
            continue
        abs_url = _text(_child(e, "id"))
        pdf = ""
        for l in _children(e, "link"):
            if l.get("title") == "pdf" or l.get("type") == "application/pdf":
                pdf = l.get("href", "")
        cats = [c.get("term") for c in _children(e, "category") if c.get("term")]
        authors = [_text(_child(a, "name")) for a in _children(e, "author")]
        comment = ""
        for c in e:
            if _local(c.tag) == "comment":
                comment = _text(c)
        it = make_item(
            source, url=abs_url, title=_text(_child(e, "title")), summary=_text(_child(e, "summary")),
            published=parse_date(_text(_child(e, "published"))), authors=authors[:12],
            extra={"pdf": canonical_url(pdf).replace("/abs/", "/pdf/") if pdf else "", "categories": cats[:5],
                   "venue": "arXiv", "comment": clean_text(comment, 200)},
        )
        if it:
            out.append(it)
    return out


def fetch_arxiv(source: dict) -> list[dict]:
    params = {
        "search_query": source["query"], "start": 0, "max_results": source.get("max_results", 50),
        "sortBy": "submittedDate", "sortOrder": "descending",
    }
    url = ARXIV_API + "?" + urllib.parse.urlencode(params)
    items = parse_arxiv(net.get_text(url, timeout=60), source)
    time.sleep(3.1)  # arXiv 要求请求间隔 ≥3 秒
    return items


def fetch_arxiv_backfill(source: dict, state: dict, log=print) -> list[dict]:
    """历史回填：每次在上次的位置继续往前翻 pages_per_fetch 页，直到早于 since 或达到 max_pages。
    进度记在 state['backfill'][source_id]；回填条目打上 backfill=True，不受 max_item_age_days 限制。"""
    bf = source.get("backfill") or {}
    prog = state.setdefault("backfill", {}).setdefault(source["id"], {"next": source.get("max_results", 50), "done": False})
    if prog.get("done"):
        return []
    since = parse_date(bf.get("since", "2023-01-01"))
    size = int(bf.get("page_size", 100))
    out: list[dict] = []
    for _ in range(int(bf.get("pages_per_fetch", 2))):
        start = int(prog["next"])
        if start >= size * int(bf.get("max_pages", 6)) + source.get("max_results", 50):
            prog["done"] = True
            break
        params = {"search_query": source["query"], "start": start, "max_results": size,
                  "sortBy": "submittedDate", "sortOrder": "descending"}
        page = parse_arxiv(net.get_text(ARXIV_API + "?" + urllib.parse.urlencode(params), timeout=60), source)
        time.sleep(3.1)
        prog["next"] = start + size
        if not page:
            prog["done"] = True
            break
        for it in page:
            pub = parse_date(it["published"])
            if since and pub and pub < since:
                prog["done"] = True
                continue
            it["backfill"] = True
            out.append(it)
        if prog["done"]:
            break
    if out:
        log(f"    回填 {source['name']}：+{len(out)} 条（下次从第 {prog['next']} 条继续{'，已完成' if prog['done'] else ''}）")
    return out


def _openalex_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def parse_openalex(data: dict, source: dict) -> list[dict]:
    out = []
    for w in data.get("results", []):
        doi = w.get("doi") or ""
        loc = (w.get("primary_location") or {})
        url = doi or loc.get("landing_page_url") or w.get("id", "")
        venue = ((loc.get("source") or {}).get("display_name")) or ""
        authors = [a.get("author", {}).get("display_name", "") for a in w.get("authorships", [])][:12]
        pdf = (w.get("open_access") or {}).get("oa_url") or ""
        it = make_item(
            source, url=url, title=w.get("display_name") or w.get("title") or "",
            summary=_openalex_abstract(w.get("abstract_inverted_index")),
            published=parse_date(w.get("publication_date")), authors=[a for a in authors if a],
            extra={"venue": venue, "pdf": pdf, "doi": doi, "cited_by": w.get("cited_by_count", 0), "type": w.get("type", "")},
        )
        if it:
            out.append(it)
    return out


def fetch_openalex(source: dict, since_days: int = 30) -> list[dict]:
    since = (now_utc() - timedelta(days=since_days)).strftime("%Y-%m-%d")
    params = {
        "search": source["query"], "filter": f"from_publication_date:{since},has_abstract:true",
        "sort": "publication_date:desc", "per-page": source.get("max_results", 40),
    }
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    return parse_openalex(net.get_json(url, timeout=60), source)


def parse_hn(data: dict, source: dict) -> list[dict]:
    out = []
    for h in data.get("hits", []):
        hn_url = f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        url = h.get("url") or hn_url
        created = datetime.fromtimestamp(h.get("created_at_i", 0), tz=timezone.utc) if h.get("created_at_i") else None
        it = make_item(source, url=url, title=h.get("title") or "", summary=h.get("story_text") or "",
                       published=created, authors=[h.get("author", "")] if h.get("author") else [],
                       extra={"points": h.get("points", 0), "comments": h.get("num_comments", 0), "discussion": hn_url},
                       kind="news")
        if it:
            out.append(it)
    return out


def fetch_hn(source: dict, since_days: int = 14) -> list[dict]:
    since = int((now_utc() - timedelta(days=since_days)).timestamp())
    params = {"query": source["query"], "tags": "story", "hitsPerPage": source.get("max_results", 30),
              "numericFilters": f"created_at_i>{since},points>3"}
    url = "https://hn.algolia.com/api/v1/search_by_date?" + urllib.parse.urlencode(params)
    return parse_hn(net.get_json(url, timeout=30), source)


def parse_github(data: dict, source: dict) -> list[dict]:
    out = []
    for r in data.get("items", []):
        desc = r.get("description") or ""
        topics = r.get("topics") or []
        it = make_item(source, url=r.get("html_url", ""), title=r.get("full_name", ""),
                       summary=(desc + (" Topics: " + ", ".join(topics) if topics else "")),
                       published=parse_date(r.get("created_at")), authors=[(r.get("owner") or {}).get("login", "")],
                       extra={"stars": r.get("stargazers_count", 0), "language": r.get("language") or "",
                              "pushed": r.get("pushed_at", "")},
                       kind="repo")
        if it:
            out.append(it)
    return out


def fetch_github(source: dict, since_days: int = 30) -> list[dict]:
    since = (now_utc() - timedelta(days=since_days)).strftime("%Y-%m-%d")
    q = f"{source['query']} created:>{since} stars:>=5"
    params = {"q": q, "sort": "stars", "order": "desc", "per_page": source.get("max_results", 30)}
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(params)
    return parse_github(net.get_json(url, timeout=30, headers={"Accept": "application/vnd.github+json"}), source)


FETCHERS = {"rss": fetch_rss, "arxiv": fetch_arxiv, "openalex": fetch_openalex, "hn": fetch_hn, "github": fetch_github}


def collect(sources: list[dict], state: dict, *, force: bool = False, log=print) -> list[dict]:
    """按各信源间隔抓取；state['last_fetch'][id] 记录上次成功时间。单个信源失败不影响其他信源。"""
    last = state.setdefault("last_fetch", {})
    errors = state.setdefault("errors", {})
    now = now_utc()
    out: list[dict] = []
    for s in sources:
        if not s.get("enabled", True):
            continue
        fn = FETCHERS.get(s["kind"])
        if not fn:
            log(f"  ! 未知信源类型 {s['kind']}（{s['id']}）")
            continue
        prev = last.get(s["id"])
        if not force and prev:
            from .config import parse_iso
            p = parse_iso(prev)
            if p and now - p < timedelta(hours=s.get("interval_hours", 2)) - timedelta(minutes=5):
                continue
        try:
            items = fn(s)
            if s.get("backfill") and s["kind"] == "arxiv":
                try:
                    items += fetch_arxiv_backfill(s, state, log)
                except Exception as exc:  # noqa: BLE001 —— 回填失败不影响正常抓取
                    log(f"    回填失败 {s['name']}：{str(exc)[:120]}")
            last[s["id"]] = iso(now)
            errors.pop(s["id"], None)
            log(f"  · {s['name']}: {len(items)} 条")
            out.extend(items)
        except Exception as exc:  # noqa: BLE001 —— 信源失败只记录
            errors[s["id"]] = {"at": iso(now), "error": str(exc)[:300]}
            log(f"  ! {s['name']} 抓取失败：{str(exc)[:160]}")
    return out
