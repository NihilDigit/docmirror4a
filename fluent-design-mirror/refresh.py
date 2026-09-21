#!/usr/bin/env python3
"""Mirror the public pages from fluent2.microsoft.design (Fluent 2 design system).

The site is an Astro build with pre-rendered HTML: the page content already
lives in each document's ``<main id="main-content">`` element, so this crawler
fetches the sitemap, downloads every listed page, converts the main content to
Markdown, and localizes the images referenced from the CDN (including the
``/_image?href=...`` optimizer URLs Astro emits).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import http.client
import html
import json
import mimetypes
import os
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, unquote, urljoin, urlparse
from urllib.request import Request, urlopen


BASE_URL = "https://fluent2.microsoft.design"
DEFAULT_OUT = Path(__file__).resolve().parent
USER_AGENT = "Bilby-FluentMirror/0.1 (+local documentation mirror)"
SITEMAP_INDEX = BASE_URL + "/sitemap-index.xml"
IMAGE_EXTENSIONS = {".apng", ".avif", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
FONT_EXTENSIONS = {".eot", ".otf", ".ttf", ".woff", ".woff2"}
VIDEO_EXTENSIONS = {".avi", ".m4v", ".mov", ".mp4", ".mkv", ".webm"}
MAX_URLS_PER_SITEMAP = 50000


class FetchFailure(RuntimeError):
    def __init__(self, url: str, message: str):
        super().__init__(f"{url}: {message}")
        self.url = url


def fetch(url: str, *, accept: str = "*/*", attempts: int = 4) -> tuple[bytes, dict[str, str]]:
    """Fetch a public resource with bounded retries and a polite user agent."""

    last_error: Exception | None = None
    # Site asset paths occasionally contain raw spaces (e.g. `/cdn/Card Image-1....png`);
    # percent-encode the path so http.client does not raise InvalidURL. "%" stays
    # safe to avoid double-encoding already-escaped segments.
    parts = urlparse(url)
    url = parts._replace(path=quote(parts.path, safe="/%")).geturl()
    for attempt in range(attempts):
        request = Request(url, headers={"Accept": accept, "User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=45) as response:
                return response.read(), {key.lower(): value for key, value in response.headers.items()}
        except HTTPError as error:
            last_error = error
            if error.code not in {408, 425, 429, 500, 502, 503, 504}:
                raise FetchFailure(url, f"HTTP {error.code}") from error
            retry_after = error.headers.get("Retry-After")
            try:
                delay = min(30.0, float(retry_after)) if retry_after else 2.0 ** attempt
            except ValueError:
                delay = 2.0 ** attempt
            time.sleep(delay)
        except (URLError, TimeoutError, OSError, http.client.HTTPException) as error:
            last_error = error
            time.sleep(min(30.0, 2.0 ** attempt))
    raise FetchFailure(url, str(last_error or "unknown fetch error"))


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_bytes(data)
    temporary.replace(path)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def discover_pages() -> tuple[list[str], str]:
    """Return (page URLs, version token) from the sitemap index."""

    index_raw, _ = fetch(SITEMAP_INDEX, accept="application/xml,text/xml,*/*")
    index_text = index_raw.decode("utf-8", errors="ignore")
    children = [loc.strip() for loc in re.findall(r"<loc>([^<]+)</loc>", index_text)]
    if not children:
        raise RuntimeError("sitemap index contains no child sitemaps")
    all_urls: list[str] = []
    lastmods: list[str] = []
    for child_url in children:
        if not child_url.startswith(BASE_URL):
            continue
        body, _ = fetch(child_url, accept="application/xml,text/xml,*/*")
        text = body.decode("utf-8", errors="ignore")
        found = [u.strip() for u in re.findall(r"<loc>([^<]+)</loc>", text)]
        found = [u for u in found if u.startswith(BASE_URL)]
        if len(found) > MAX_URLS_PER_SITEMAP:
            raise RuntimeError(f"{child_url} lists an implausible number of URLs")
        all_urls.extend(found)
        lastmods.extend(re.findall(r"<lastmod>([^<]+)</lastmod>", text))
    seen: set[str] = set()
    unique: list[str] = []
    for url in all_urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    version = max(lastmods) if lastmods else "unknown"
    return sorted(unique), version


def page_slug(url: str) -> str:
    return urlparse(url).path.strip("/") or "index"


def page_path(out: Path, url: str) -> Path:
    slug = page_slug(url)
    return out / "pages" / (slug + ".md" if slug != "index" else "index.md")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def escape_table(value: str) -> str:
    return normalize_text(value).replace("|", "\\|").replace("\n", " ")


def clean_markdown(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"\n[ \t]+\n", "\n\n", value)
    value = re.sub(r"(?m)^([*-]|\d+\.)[ \t]*\n(?:[ \t]*\n)?[ \t]*(?=\S)", r"\1 ", value)
    value = re.sub(r"(?m)^([-*] .+)\n\n(?=^[-*] )", r"\1\n", value)
    value = re.sub(r"(?m)^(\d+\. .+)\n\n(?=^\d+\. )", r"\1\n", value)
    return value.strip() + "\n"


def unwrap_optimizer_url(url: str) -> str:
    """Astro emits /_image?href=<url>&w=..&h=..&f=.. URLs; return the CDN href."""

    parsed = urlparse(url)
    if parsed.path == "/_image" or parsed.path.endswith("/_image"):
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        href = query.get("href")
        if href:
            return unquote(href)
    return url


def asset_kind(url: str) -> str | None:
    extension = Path(urlparse(url).path).suffix.lower()
    if extension in FONT_EXTENSIONS:
        return None  # fonts belong to the site shell, not the content corpus
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension in VIDEO_EXTENSIONS:
        return "video"
    return None


def content_asset_url(url: str) -> tuple[str, str] | None:
    """Map an HTML asset reference to a (downloadable URL, kind) pair, or None."""

    url = html.unescape(url).strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme in {"data", "mailto", "tel", "javascript"}:
        return None
    if not parsed.scheme:
        url = urljoin(BASE_URL, url)
    url = unwrap_optimizer_url(url)
    kind = asset_kind(url)
    if kind is None:
        return None
    return url, kind


VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
BLOCK_TAGS = {"address", "article", "aside", "blockquote", "div", "figure", "figcaption", "footer", "header", "main", "nav", "p", "section"}
SKIP_TAGS = {"script", "style", "template", "astro-island"}


class MainContentExtractor(HTMLParser):
    """Collect asset URLs and the <main id="main-content"> fragment.

    Uses a stack of open tags rather than absolute depth, so unmatched void or
    SVG self-closing tags elsewhere in the document cannot desynchronise the
    capture of the main element.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.title = ""
        self.main_html = ""
        self.assets: set[tuple[str, str]] = set()
        self._in_title = False
        self._capturing = False
        self._stack: list[str] = []
        self._buffer: list[str] = []

    def _record_asset(self, attrs: dict[str, str]) -> None:
        for key in ("src", "poster"):
            raw = attrs.get(key)
            if raw:
                found = content_asset_url(raw)
                if found:
                    self.assets.add(found)
        srcset = attrs.get("srcset")
        if srcset:
            for candidate in srcset.split(","):
                raw = candidate.strip().split(" ")[0] if candidate.strip() else ""
                if raw:
                    found = content_asset_url(raw)
                    if found:
                        self.assets.add(found)

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {key: (value or "") for key, value in attrs_list}
        if tag == "title":
            self._in_title = True
        self._record_asset(attrs)
        if not self._capturing and tag == "main" and attrs.get("id") == "main-content":
            self._capturing = True
            self._stack = []
            self._buffer = []
            return
        if self._capturing:
            self._buffer.append(self.get_starttag_text() or "")
            if tag not in VOID_TAGS:
                self._stack.append(tag)

    def handle_startendtag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {key: (value or "") for key, value in attrs_list}
        self._record_asset(attrs)
        if self._capturing:
            self._buffer.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if not self._capturing:
            return
        if tag == "main" and not self._stack:
            self.main_html = "".join(self._buffer)
            self._buffer = []
            self._capturing = False
            return
        self._buffer.append(f"</{tag}>")
        if tag in VOID_TAGS:
            return
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()
        elif tag in self._stack:
            # Tolerate mis-nested markup: drop back to the matching open tag.
            while self._stack and self._stack[-1] != tag:
                self._stack.pop()
            if self._stack:
                self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._capturing:
            self._buffer.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._capturing:
            self._buffer.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._capturing:
            self._buffer.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        if self._capturing and data.strip() in {"astro:end"}:
            self._buffer.append(f"<!--{data}-->")



class HtmlToMarkdown(HTMLParser):
    """Small dependency-free HTML-to-Markdown converter for page content."""

    def __init__(self, resolver) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.resolver = resolver
        self.list_stack: list[str] = []
        self.link_stack: list[str] = []
        self.skip_stack: list[str] = []
        self.pre_depth = 0
        self.cell_parts: list[str] | None = None
        self.row_cells: list[str] | None = None
        self.table_rows: list[list[str]] | None = None

    def block(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n\n"):
            if self.parts[-1].endswith("\n"):
                self.parts[-1] += "\n"
            else:
                self.parts.append("\n\n")

    def line(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def text(self, value: str) -> None:
        if self.cell_parts is not None:
            self.cell_parts.append(value)
        else:
            self.parts.append(value)

    def skipping(self) -> bool:
        return bool(self.skip_stack)

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        if self.skipping():
            if tag in SKIP_TAGS:
                self.skip_stack.append(tag)
            return
        attrs = {key: (value or "") for key, value in attrs_list}
        if tag in SKIP_TAGS:
            self.skip_stack.append(tag)
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.block()
            self.parts.append("#" * int(tag[1]) + " ")
        elif tag in BLOCK_TAGS:
            self.block()
        elif tag == "br":
            self.line()
        elif tag == "hr":
            self.block()
            self.parts.append("---")
            self.block()
        elif tag in {"ul", "ol"}:
            self.block()
            self.list_stack.append(tag)
        elif tag == "li":
            self.line()
            marker = "- "
            if self.list_stack and self.list_stack[-1] == "ol":
                marker = "1. "
            self.parts.append("  " * (len(self.list_stack) - 1) + marker)
        elif tag == "pre":
            self.block()
            self.pre_depth += 1
            self.parts.append("```\n")
        elif tag == "code" and not self.pre_depth:
            self.parts.append("`")
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag == "a":
            href = attrs.get("href", "")
            self.link_stack.append(href)
            self.parts.append("[")
        elif tag == "img":
            src = attrs.get("src", "")
            alt = attrs.get("alt", "")
            resolved = self.resolver(src) if src else ""
            if resolved:
                self.block()
                self.parts.append(f"![{normalize_text(alt)}]({resolved})")
                self.block()
        elif tag == "video":
            src = attrs.get("src", "") or attrs.get("poster", "")
            resolved = self.resolver(src) if src else ""
            if resolved:
                self.block()
                self.parts.append(f"[video]({resolved})")
                self.block()
        elif tag == "table":
            self.block()
            self.table_rows = []
        elif tag == "tr":
            if self.table_rows is not None:
                self.row_cells = []
        elif tag in {"thead", "tbody", "tfoot"}:
            # <thead> may wrap <th> cells directly without a <tr>; start a row.
            if tag == "thead" and self.table_rows is not None and self.row_cells is None:
                self.row_cells = []
        elif tag in {"td", "th"}:
            if self.table_rows is not None and self.row_cells is None:
                self.row_cells = []
            if self.row_cells is not None:
                self.cell_parts = []


    def handle_startendtag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        if self.skipping():
            return
        if tag == "img":
            attrs = {key: (value or "") for key, value in attrs_list}
            src = attrs.get("src", "")
            alt = attrs.get("alt", "")
            resolved = self.resolver(src) if src else ""
            if resolved:
                self.block()
                self.parts.append(f"![{normalize_text(alt)}]({resolved})")
                self.block()
        elif tag in {"source", "track"}:
            return
        else:
            self.handle_starttag(tag, attrs_list)
            if tag not in VOID_TAGS:
                self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.skipping():
            if self.skip_stack and self.skip_stack[-1] == tag:
                self.skip_stack.pop()
            return
        if tag in SKIP_TAGS:
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} or tag in BLOCK_TAGS:
            self.block()
        elif tag in {"ul", "ol"}:
            if self.list_stack:
                self.list_stack.pop()
            self.block()
        elif tag == "li":
            self.line()
        elif tag == "pre":
            self.pre_depth = max(0, self.pre_depth - 1)
            self.parts.append("\n```")
            self.block()
        elif tag == "code" and not self.pre_depth:
            self.parts.append("`")
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag == "a":
            href = self.link_stack.pop() if self.link_stack else ""
            self.parts.append("]")
            if href and not href.startswith("#"):
                parsed = urlparse(html.unescape(href))
                if parsed.scheme in {"http", "https", ""}:
                    self.parts.append(f"({href})")
        elif tag in {"td", "th"}:
            if self.cell_parts is not None and self.row_cells is not None:
                self.row_cells.append(escape_table("".join(self.cell_parts)))
            self.cell_parts = None
        elif tag == "tr":
            if self.row_cells is not None and self.table_rows is not None:
                self.table_rows.append(self.row_cells)
            self.row_cells = None
        elif tag in {"thead", "tbody", "tfoot"}:
            if self.row_cells is not None and self.table_rows is not None:
                self.table_rows.append(self.row_cells)
            self.row_cells = None
        elif tag == "table":
            if self.table_rows:
                width = max((len(row) for row in self.table_rows), default=0)
                rows = [row + [""] * (width - len(row)) for row in self.table_rows if row]
                if rows:
                    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join("---" for _ in rows[0]) + " |"]
                    lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
                    self.block()
                    self.parts.append("\n".join(lines))
            self.table_rows = None
            self.block()

    def handle_data(self, data: str) -> None:
        if self.skipping():
            return
        if self.pre_depth:
            self.text(data)
        else:
            value = normalize_text(data)
            if value:
                self.text(value + " ")

    def markdown(self) -> str:
        return clean_markdown("".join(self.parts))


def relative_posix(target: Path, start: Path) -> str:
    return Path(os.path.relpath(target, start)).as_posix()


def local_asset_path(url: str) -> str:
    """Deterministic assets/ location for a remote asset URL."""

    parsed = urlparse(url)
    extension = Path(parsed.path).suffix.lower()
    if not extension or len(extension) > 5:
        extension = ".bin"
    digest = sha256(url.encode("utf-8"))[:16]
    stem = Path(parsed.path).stem or "asset"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem)[:60].strip("-.") or "asset"
    return f"assets/{stem}-{digest}{extension}"


def download_asset(url: str, kind: str, out: Path) -> dict:
    local = local_asset_path(url)
    target = out / local
    record = {"url": url, "kind": kind, "path": local, "status": "error"}
    try:
        data, headers = fetch(url, accept="image/*,video/*,*/*")
        write_bytes(target, data)
        record["status"] = "downloaded"
        record["bytes"] = len(data)
        record["sha256"] = sha256(data)
        record["content_type"] = headers.get("content-type", "")
    except Exception as error:  # one bad asset must not kill the run; recorded in metadata/assets.json
        record["error"] = f"{type(error).__name__}: {error}"
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="mirror output directory (default: script directory)")
    parser.add_argument("--workers", type=int, default=8, help="parallel fetch workers")
    parser.add_argument("--no-assets", action="store_true", help="rebuild Markdown only; reuse already-downloaded assets")
    parser.add_argument("--refresh", action="store_true", help="re-download assets even when already cached")
    parser.add_argument("--keep-html", action="store_true", help="keep raw page HTML under metadata/raw-pages/ for debugging")
    args = parser.parse_args()

    out: Path = args.out.resolve()
    metadata = out / "metadata"
    pages_dir = out / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    metadata.mkdir(parents=True, exist_ok=True)

    urls, version = discover_pages()
    print(f"discovered {len(urls)} pages (version: {version})", file=sys.stderr)

    page_records: list[dict] = []
    raw_html: dict[str, str] = {}

    def load_page(url: str) -> tuple[str, str | None, str | None]:
        try:
            data, _headers = fetch(url, accept="text/html,application/xhtml+xml")
            return url, data.decode("utf-8", errors="replace"), None
        except FetchFailure as error:
            return url, None, str(error)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for url, html_text, error in pool.map(load_page, urls):
            record = {"url": url, "slug": page_slug(url)}
            if error or html_text is None:
                record["status"] = "error"
                record["error"] = error or "empty response"
            else:
                record["status"] = "ok"
                record["html_bytes"] = len(html_text.encode("utf-8"))
                raw_html[url] = html_text
            page_records.append(record)

    # First pass: collect every asset referenced by any page.
    asset_urls: dict[str, str] = {}
    extractors: dict[str, MainContentExtractor] = {}
    for url, html_text in raw_html.items():
        extractor = MainContentExtractor()
        extractor.feed(html_text)
        extractor.close()
        extractors[url] = extractor
        for remote, kind in extractor.assets:
            asset_urls.setdefault(remote, kind)
    print(f"found {len(asset_urls)} unique content assets", file=sys.stderr)

    # Second pass: download assets (or reuse cache) and build the asset map.
    assets_manifest = metadata / "assets.json"
    previous: dict[str, dict] = {}
    if assets_manifest.exists() and not args.refresh:
        try:
            for record in json.loads(assets_manifest.read_text(encoding="utf-8")):
                previous[record["url"]] = record
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            previous = {}

    asset_records: list[dict] = []
    pending: list[tuple[str, str]] = []
    for url, kind in sorted(asset_urls.items()):
        prior = previous.get(url)
        if prior and not args.refresh and prior.get("path") and (out / prior["path"]).exists():
            record = dict(prior)
            record["status"] = "cached"
            asset_records.append(record)
        else:
            pending.append((url, kind))

    if pending and not args.no_assets:
        print(f"downloading {len(pending)} assets", file=sys.stderr)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = [pool.submit(download_asset, url, kind, out) for url, kind in pending]
            for future in concurrent.futures.as_completed(futures):
                asset_records.append(future.result())
    else:
        for url, kind in pending:
            record = {"url": url, "kind": kind, "path": local_asset_path(url), "status": "not-downloaded"}
            if (out / record["path"]).exists():
                record["status"] = "cached"
            asset_records.append(record)

    asset_records.sort(key=lambda record: record["url"])
    write_json(assets_manifest, asset_records)
    asset_map = {
        record["url"]: record["path"]
        for record in asset_records
        if record.get("path") and record.get("status") in {"downloaded", "cached"}
    }


    # Third pass: render Markdown with localized asset references.
    markdown_count = 0
    for record in page_records:
        url = record["url"]
        html_text = raw_html.get(url)
        if html_text is None:
            continue
        extractor = extractors[url]
        body = extractor.main_html
        if not body:
            # Pages behind the employee sign-in wall return a login shell with
            # no <main>; skip them instead of treating as fetch errors.
            record["status"] = "skipped"
            record["error"] = "no public <main id=\"main-content\"> (likely employee sign-in)"
            continue
        title = normalize_text(extractor.title)
        title = title.removesuffix(" - Fluent 2 Design System").strip() or record["slug"]
        markdown_path = page_path(out, url)

        def resolver(raw: str, _path: Path = markdown_path) -> str:
            found = content_asset_url(raw)
            if not found:
                return ""
            remote, _kind = found
            local = asset_map.get(remote)
            if local:
                try:
                    return relative_posix(out / local, _path.parent)
                except ValueError:
                    return (out / local).as_posix()
            return remote

        converter = HtmlToMarkdown(resolver)
        converter.feed(body)
        converter.close()
        markdown = converter.markdown()
        header = f"---\nsource: {url}\ntitle: {json.dumps(title, ensure_ascii=False)}\n---\n\n"
        final = header + markdown
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(final, encoding="utf-8")
        record["markdown"] = markdown_path.relative_to(out).as_posix()
        record["markdown_bytes"] = len(final.encode("utf-8"))
        record["title"] = title
        markdown_count += 1
        if args.keep_html:
            slug = record["slug"]
            raw_path = metadata / "raw-pages" / (slug + ".html" if slug != "index" else "index.html")
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(html_text, encoding="utf-8")

    write_json(metadata / "pages.json", sorted(page_records, key=lambda r: r["url"]))

    manifest = {
        "source": BASE_URL,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "site_lastmod": version,
        "page_count": len([r for r in page_records if r.get("status") == "ok"]),
        "page_error_count": len([r for r in page_records if r.get("status") == "error"]),
        "page_skipped_count": len([r for r in page_records if r.get("status") == "skipped"]),
        "markdown_count": markdown_count,
        "asset_count": len(asset_records),
        "asset_downloaded_count": len([r for r in asset_records if r.get("status") in {"downloaded", "cached"}]),
        "asset_error_count": len([r for r in asset_records if r.get("status") == "error"]),
        "notes": [
            "Generated data is intentionally kept outside Git via .git/info/exclude.",
            "Only public pages listed in the sitemap are mirrored; employee sign-in content is excluded.",
            "Interactive Astro islands (live component demos) are rendered as static SSR content only.",
            "Review the source site's terms and each asset's license before redistribution.",
        ],
    }
    write_json(out / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)

