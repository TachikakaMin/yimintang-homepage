#!/usr/bin/env python3
"""Create a self-contained static snapshot of Yimin Tang's Google Site.

The original Google Sites HTML and CSS are preserved. Runtime scripts are
removed, remote presentation assets are downloaded, public Drive documents are
localized, and video embeds receive local media/posters so the rendered page no
longer depends on Google being reachable.
"""

from __future__ import annotations

import hashlib
import html
import json
import mimetypes
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://sites.google.com/view/yimintang/"
PAGES_URL = "https://tachikakamin.github.io/yimintang-homepage/"
ASSET_DIR = ROOT / "assets" / "mirror"
INDEX_FILE = ROOT / "index.html"
STATE_FILE = ROOT / "sync-state.json"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"
)


def fetch(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read(), response.headers.get_content_type()


def extension_for(content_type: str, data: bytes) -> str:
    signatures = (
        (b"%PDF", ".pdf"),
        (b"\x89PNG\r\n\x1a\n", ".png"),
        (b"\xff\xd8\xff", ".jpg"),
        (b"GIF8", ".gif"),
        (b"\x00\x00\x00", ".mov"),
        (b"wOFF", ".woff"),
        (b"wOF2", ".woff2"),
    )
    for signature, extension in signatures:
        if data.startswith(signature):
            return extension
    guessed = mimetypes.guess_extension(content_type) or ".bin"
    return ".jpg" if guessed == ".jpe" else guessed


class SnapshotBuilder:
    def __init__(self, staging_dir: Path):
        self.staging_dir = staging_dir
        self.url_cache: dict[str, str] = {}

    def save_asset(self, url: str, prefix: str = "asset") -> str:
        url = html.unescape(url)
        if url in self.url_cache:
            return self.url_cache[url]
        try:
            data, content_type = fetch(url)
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            print(f"warning: could not download {url}: {error}", file=sys.stderr)
            return url

        if content_type == "text/html" and prefix in {
            "background",
            "css-asset",
            "drive-poster",
            "icon",
            "image",
            "social",
            "youtube",
        }:
            # Some Google Drive thumbnail URLs return an account/login page to
            # non-browser clients. Keep the layout box without shipping HTML as
            # an image asset or leaving a Google runtime request behind.
            data = (
                b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1" '
                b'viewBox="0 0 1 1"></svg>'
            )
            content_type = "image/svg+xml"

        digest = hashlib.sha256(data).hexdigest()[:16]
        filename = f"{prefix}-{digest}{extension_for(content_type, data)}"
        (self.staging_dir / filename).write_bytes(data)
        local = f"assets/mirror/{filename}"
        self.url_cache[url] = local
        return local

    def localize_css(self, url: str) -> str:
        url = html.unescape(url)
        if url in self.url_cache:
            return self.url_cache[url]
        try:
            data, _content_type = fetch(url)
            css = data.decode("utf-8")
        except (urllib.error.URLError, UnicodeDecodeError, TimeoutError) as error:
            print(f"warning: could not download stylesheet {url}: {error}", file=sys.stderr)
            return url

        base_url = url

        def replace_css_url(match: re.Match[str]) -> str:
            quote, value = match.group(1), html.unescape(match.group(2))
            if value.startswith("data:"):
                return match.group(0)
            absolute = urllib.parse.urljoin(base_url, value)
            local = self.save_asset(absolute, "css-asset")
            # CSS assets live beside the generated stylesheet. Keep these URLs
            # relative to the stylesheet itself rather than to index.html.
            return f"url({quote}{Path(local).name}{quote})"

        css = re.sub(r"url\(([\"']?)([^)\"']+)\1\)", replace_css_url, css, flags=re.I)
        digest = hashlib.sha256(css.encode("utf-8")).hexdigest()[:16]
        filename = f"style-{digest}.css"
        (self.staging_dir / filename).write_text(css, encoding="utf-8")
        local = f"assets/mirror/{filename}"
        self.url_cache[url] = local
        return local

    def localize_drive_url(self, url: str, prefix: str = "document") -> str | None:
        decoded = html.unescape(url)
        match = re.search(r"drive\.google\.com/(?:file/d/|open\?id=|uc\?id=)([^/&?]+)", decoded)
        if not match:
            return None
        file_id = match.group(1)
        download_url = (
            "https://drive.usercontent.google.com/download?"
            + urllib.parse.urlencode({"id": file_id, "export": "download", "confirm": "t"})
        )
        return self.save_asset(download_url, prefix)

    def replace_stylesheet(self, match: re.Match[str]) -> str:
        before, url, after = match.group(1), html.unescape(match.group(2)), match.group(3)
        if "stylesheet" not in (before + after).lower():
            return match.group(0)
        local = self.localize_css(url)
        return f'<link {before}href="{local}"{after}>'

    def replace_image(self, match: re.Match[str]) -> str:
        return match.group(1) + self.save_asset(match.group(2), "image") + match.group(3)

    def replace_inline_url(self, match: re.Match[str]) -> str:
        quote, url = match.group(1), match.group(2)
        local = self.save_asset(url, "background")
        return f"url({quote}{local}{quote})"

    def replace_icon(self, match: re.Match[str]) -> str:
        before, url, after = match.group(1), match.group(2), match.group(3)
        return f'<link {before}href="{self.save_asset(url, "icon")}"{after}>'

    def replace_meta_image(self, match: re.Match[str]) -> str:
        before, url, after = match.group(1), match.group(2), match.group(3)
        return f'<meta {before}content="{self.save_asset(url, "social")}"{after}>'

    def replace_anchor(self, match: re.Match[str]) -> str:
        before, url, after = match.group(1), html.unescape(match.group(2)), match.group(3)
        drive_local = self.localize_drive_url(url)
        if drive_local:
            return f'<a {before}href="{drive_local}"{after}>'

        parsed = urllib.parse.urlparse(url)
        if parsed.netloc in {"google.com", "www.google.com"} and parsed.path == "/url":
            url = urllib.parse.parse_qs(parsed.query).get("q", [url])[0]
        return f'<a {before}href="{html.escape(url, quote=True)}"{after}>'

    def replace_youtube_iframe(self, match: re.Match[str]) -> str:
        attributes = match.group(1)
        src_match = re.search(
            r"src=[\"']https://www\.youtube\.com/embed/([^?&/\"']+)[^\"']*[\"']",
            attributes,
        )
        if not src_match:
            return match.group(0)
        video_id = src_match.group(1)
        label_match = re.search(r"aria-label=[\"']([^\"']+)[\"']", attributes)
        label = label_match.group(1) if label_match else "YouTube video"
        poster = self.save_asset(f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg", "youtube")
        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        return (
            f'<a class="YMEQtf mirror-video" href="{watch_url}" target="_blank" '
            f'rel="noopener" aria-label="{html.escape(label, quote=True)}">'
            f'<img src="{poster}" alt="{html.escape(label, quote=True)}">'
            '<span aria-hidden="true">▶</span></a>'
        )

    def replace_drive_iframe(self, match: re.Match[str]) -> str:
        attributes = match.group(1)
        source_match = re.search(
            r"data-src=[\"'](https://drive\.google\.com/file/d/[^\"']+)[\"']", attributes
        )
        if not source_match:
            return match.group(0)
        video = self.localize_drive_url(source_match.group(1), "video")
        if not video:
            return match.group(0)

        label_match = re.search(r"aria-label=[\"']([^\"']+)[\"']", attributes)
        label = label_match.group(1) if label_match else "Embedded video"
        doc_id_match = re.search(r"/file/d/([^/]+)", source_match.group(1))
        poster = ""
        if doc_id_match:
            thumbnail = f"https://lh3.google.com/u/0/d/{doc_id_match.group(1)}=s2048"
            local_poster = self.save_asset(thumbnail, "drive-poster")
            if not local_poster.startswith("http"):
                poster = f' poster="{local_poster}"'
        return (
            f'<video class="YMEQtf mirror-drive-video" controls preload="metadata"'
            f' src="{video}"{poster} aria-label="{html.escape(label, quote=True)}"></video>'
        )

    def build(self, source_html: str) -> str:
        page = source_html

        # Google Sites ships fully rendered semantic content, so its JavaScript
        # can be removed without losing the page body.
        page = re.sub(r"<script\b[^>]*>.*?</script\s*>", "", page, flags=re.S | re.I)
        page = re.sub(
            r"<link\b(?=[^>]*\b(?:as=[\"']script[\"']|rel=[\"'](?:modulepreload|preload)[\"']))[^>]*>",
            "",
            page,
            flags=re.I,
        )
        page = re.sub(
            r"<link\b[^>]*\brel=[\"'](?:preconnect|dns-prefetch)[\"'][^>]*>",
            "",
            page,
            flags=re.I,
        )
        page = re.sub(r"\snonce=[\"'][^\"']*[\"']", "", page, flags=re.I)

        page = re.sub(
            r"<link\s+([^>]*?)href=[\"'](https://[^\"']+)[\"']([^>]*)>",
            self.replace_stylesheet,
            page,
            flags=re.I,
        )
        page = re.sub(
            r"<link\s+([^>]*?rel=[\"'](?:icon|apple-touch-icon)[\"'][^>]*?)href=[\"'](https://[^\"']+)[\"']([^>]*)>",
            self.replace_icon,
            page,
            flags=re.I,
        )
        page = re.sub(
            r"<meta\s+([^>]*(?:property=[\"']og:image[\"']|itemprop=[\"'](?:thumbnailUrl|image|imageUrl)[\"'])[^>]*?)content=[\"'](https://[^\"']+)[\"']([^>]*)>",
            self.replace_meta_image,
            page,
            flags=re.I,
        )
        page = re.sub(
            r"(<img\b[^>]*?\bsrc=[\"'])(https://[^\"']+)([\"'])",
            self.replace_image,
            page,
            flags=re.I,
        )
        page = re.sub(
            r"url\(([\"']?)(https://[^)\"']+)\1\)",
            self.replace_inline_url,
            page,
            flags=re.I,
        )

        page = re.sub(
            r"<iframe\b([^>]*src=[\"']https://www\.youtube\.com/embed/[^>]+)></iframe>",
            self.replace_youtube_iframe,
            page,
            flags=re.I,
        )
        page = re.sub(
            r"<iframe\b([^>]*data-src=[\"']https://drive\.google\.com/file/d/[^>]+)></iframe>",
            self.replace_drive_iframe,
            page,
            flags=re.I,
        )
        page = re.sub(
            r"<a\s+([^>]*?)href=[\"'](https://[^\"']+)[\"']([^>]*)>",
            self.replace_anchor,
            page,
            flags=re.I,
        )

        page = page.replace(
            "</head>",
            """
<style>
.mirror-video { display: block !important; overflow: hidden; background: #111; text-decoration: none; }
.mirror-video img { width: 100%; height: 100%; object-fit: cover; }
.mirror-video span { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); display: grid; place-items: center; width: 64px; height: 46px; color: white; background: #e62117; border-radius: 12px; font-size: 24px; box-shadow: 0 4px 16px rgba(0,0,0,.28); }
.mirror-drive-video { width: 100%; height: 100%; object-fit: contain; background: #111; }
</style>
</head>""",
            1,
        )
        page = page.replace(SOURCE_URL, PAGES_URL)
        return page


def publish_assets(staging_dir: Path, rendered: str) -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    referenced = {
        path.name
        for path in staging_dir.iterdir()
        if path.is_file() and f"assets/mirror/{path.name}" in rendered
    }
    # Stylesheets can reference local font and image files of their own.
    for stylesheet in staging_dir.glob("*.css"):
        if stylesheet.name not in referenced:
            continue
        css = stylesheet.read_text(encoding="utf-8")
        referenced.update(
            match.group(1)
            for match in re.finditer(r"url\([\"']?([^)'\"\s]+)", css)
            if not match.group(1).startswith(("data:", "http://", "https://"))
        )
    for existing in ASSET_DIR.iterdir():
        if existing.is_file() and existing.name not in referenced:
            existing.unlink()
    for staged in staging_dir.iterdir():
        if staged.name not in referenced:
            continue
        destination = ASSET_DIR / staged.name
        if not destination.exists() or destination.read_bytes() != staged.read_bytes():
            shutil.copy2(staged, destination)


def main() -> None:
    source_bytes, _content_type = fetch(SOURCE_URL)
    with tempfile.TemporaryDirectory(prefix="yimin-google-site-") as temporary:
        staging_dir = Path(temporary)
        builder = SnapshotBuilder(staging_dir)
        rendered = builder.build(source_bytes.decode("utf-8"))
        if "Short Bio" not in rendered or "PAPER LIST" not in rendered:
            raise RuntimeError("Google Sites markup changed; refusing to replace the known-good snapshot")

        publish_assets(staging_dir, rendered)
        INDEX_FILE.write_text(rendered, encoding="utf-8")
        state = {
            "source": SOURCE_URL,
            "mode": "original-static-snapshot",
            "content_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
            "assets": len(list(ASSET_DIR.iterdir())),
        }
        STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Built original-layout snapshot with {state['assets']} local assets")


if __name__ == "__main__":
    main()
