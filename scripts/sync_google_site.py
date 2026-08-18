#!/usr/bin/env python3
"""Build a Google-independent snapshot of Yimin Tang's public Google Site.

Only Python's standard library is used so the script can run unchanged in
GitHub Actions. The generated fragment is intentionally presentation-neutral;
the main site's CSS supplies the layout.
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
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://sites.google.com/view/yimintang/"
GENERATED_DIR = ROOT / "assets" / "generated"
CONTENT_FILE = ROOT / "content.html"
STATE_FILE = ROOT / "sync-state.json"
USER_AGENT = "Mozilla/5.0 (compatible; YiminTangHomepageMirror/1.0)"

BLOCK_TAGS = {"h1", "h2", "h3", "h4", "p", "ul", "ol", "li", "blockquote"}
INLINE_TAGS = {"strong", "b", "em", "i", "code", "small", "sup", "sub"}
VOID_TAGS = {"br"}
ALLOWED_TAGS = BLOCK_TAGS | INLINE_TAGS | VOID_TAGS


def fetch(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read(), response.headers.get_content_type()


def extension_for(content_type: str, data: bytes) -> str:
    signatures = (
        (b"%PDF", ".pdf"),
        (b"\x89PNG\r\n\x1a\n", ".png"),
        (b"\xff\xd8\xff", ".jpg"),
        (b"GIF8", ".gif"),
        (b"RIFF", ".webp"),
    )
    for signature, extension in signatures:
        if data.startswith(signature):
            return extension
    guessed = mimetypes.guess_extension(content_type) or ".bin"
    return ".jpg" if guessed == ".jpe" else guessed


def save_asset(url: str, prefix: str, staging_dir: Path) -> str | None:
    try:
        data, content_type = fetch(url)
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        print(f"warning: could not download {url}: {error}", file=sys.stderr)
        return None

    digest = hashlib.sha256(data).hexdigest()[:16]
    filename = f"{prefix}-{digest}{extension_for(content_type, data)}"
    (staging_dir / filename).write_bytes(data)
    return f"assets/generated/{filename}"


def unwrap_google_redirect(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc in {"www.google.com", "google.com"} and parsed.path == "/url":
        query = urllib.parse.parse_qs(parsed.query)
        return query.get("q", [url])[0]
    return url


def drive_download_url(url: str) -> str | None:
    match = re.search(r"drive\.google\.com/file/d/([^/]+)", url)
    if not match:
        return None
    file_id = match.group(1)
    return (
        "https://drive.usercontent.google.com/download?"
        + urllib.parse.urlencode({"id": file_id, "export": "download", "confirm": "t"})
    )


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "section"


class GoogleSiteParser(HTMLParser):
    def __init__(self, staging_dir: Path):
        super().__init__(convert_charrefs=True)
        self.staging_dir = staging_dir
        self.capture = False
        self.capture_depth = 0
        self.fragments: list[tuple[str, str]] = []
        self.output: list[str] = []
        self.text: list[str] = []
        self.emitted_stack: list[tuple[str, bool]] = []
        self.skip_depth = 0
        self.image_index = 0
        self.document_index = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        classes = set(attr.get("class", "").split())

        if not self.capture and tag == "div" and "tyJCtd" in classes:
            self.capture = True
            self.capture_depth = 1
            self.output = []
            self.text = []
            self.emitted_stack = []
            return

        if not self.capture:
            return

        if tag == "div":
            self.capture_depth += 1

        if self.skip_depth:
            self.skip_depth += 1
            return

        if tag == "a":
            aria_label = attr.get("aria-label", "")
            href = attr.get("href", "")
            if aria_label == "Copy heading link" or href.startswith("#h."):
                self.skip_depth = 1
                self.emitted_stack.append((tag, False))
                return
            href = unwrap_google_redirect(href)
            if not href:
                self.emitted_stack.append((tag, False))
                return
            local = self.localize_drive_file(href)
            href = local or href
            self.output.append(
                f'<a href="{html.escape(href, quote=True)}"'
                + ("" if href.startswith(("#", "/", "assets/")) else ' target="_blank" rel="noopener"')
                + ">"
            )
            self.emitted_stack.append((tag, True))
            return

        if tag == "img":
            src = attr.get("src", "")
            if not src or "images/icons/product/drive" in src:
                return
            local = save_asset(src, f"image-{self.image_index:02}", self.staging_dir)
            image_class = self.image_class(self.image_index)
            self.image_index += 1
            if local:
                alt = attr.get("alt", "") or "Image from Yimin Tang's homepage"
                self.output.append(
                    f'<img class="{image_class}" src="{local}" '
                    f'alt="{html.escape(alt, quote=True)}" loading="lazy" decoding="async">'
                )
            return

        if tag == "iframe":
            src = attr.get("src", "")
            match = re.search(r"youtube\.com/embed/([^?&/]+)", src)
            if match:
                video_id = match.group(1)
                watch_url = f"https://www.youtube.com/watch?v={video_id}"
                self.output.append(
                    '<div class="video-placeholder"><span>Video</span>'
                    f'<a href="{watch_url}" target="_blank" rel="noopener">'
                    "Open on YouTube ↗</a></div>"
                )
            return

        if tag in ALLOWED_TAGS:
            if tag in VOID_TAGS:
                self.output.append(f"<{tag}>")
                return
            tag_id = ""
            if tag in {"h2", "h3"}:
                original_id = attr.get("id", "")
                if original_id:
                    tag_id = f' id="{html.escape(original_id, quote=True)}"'
            self.output.append(f"<{tag}{tag_id}>")
            self.emitted_stack.append((tag, True))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if not self.capture:
            return

        if self.skip_depth:
            self.skip_depth -= 1
            if tag == "a" and self.emitted_stack and self.emitted_stack[-1][0] == "a":
                self.emitted_stack.pop()
            return

        if tag == "div":
            self.capture_depth -= 1
            if self.capture_depth == 0:
                self.finish_fragment()
                self.capture = False
                return

        if tag in ALLOWED_TAGS or tag == "a":
            for index in range(len(self.emitted_stack) - 1, -1, -1):
                open_tag, emitted = self.emitted_stack[index]
                if open_tag == tag:
                    self.emitted_stack.pop(index)
                    if emitted:
                        self.output.append(f"</{tag}>")
                    break

    def handle_data(self, data: str) -> None:
        if self.capture and not self.skip_depth:
            self.output.append(html.escape(data))
            self.text.append(data)

    def finish_fragment(self) -> None:
        normalized_text = re.sub(r"\s+", " ", " ".join(self.text)).strip()
        rendered = "".join(self.output).strip()
        if rendered and (normalized_text or "<img " in rendered or "video-placeholder" in rendered):
            self.fragments.append((normalized_text, rendered))

    def localize_drive_file(self, href: str) -> str | None:
        download_url = drive_download_url(href)
        if not download_url:
            return None
        return save_asset(download_url, "document", self.staging_dir)

    @staticmethod
    def image_class(index: int) -> str:
        if index == 0:
            return "source-image source-image--accent"
        if 1 <= index <= 7:
            return "source-image source-image--logo"
        if index == 12:
            return "source-image source-image--animation"
        return "source-image source-image--figure"

    def render(self) -> str:
        start = 0
        for index, (text, _fragment) in enumerate(self.fragments):
            if text.strip().lower() == "short bio":
                start = index
                break

        sections: list[str] = []
        heading_counts: dict[str, int] = {}
        for text, fragment in self.fragments[start:]:
            if text.strip().lower() in {"page updated", "google sites", "report abuse"}:
                continue
            if re.fullmatch(r"[^<>\n]+\.(?:mov|mp4|avi)", text.strip(), flags=re.I):
                continue
            heading_match = re.search(r"<(h[23])(?: [^>]*)?>(.*?)</\1>", fragment, flags=re.S)
            if heading_match:
                heading_text = re.sub(r"<[^>]+>", "", heading_match.group(2))
                heading_text = html.unescape(heading_text).strip()
                base = slugify(heading_text)
                count = heading_counts.get(base, 0) + 1
                heading_counts[base] = count
                heading_id = base if count == 1 else f"{base}-{count}"
                fragment = re.sub(
                    r"<(h[23])(?: [^>]*)?>",
                    lambda match: f'<{match.group(1)} id="{heading_id}">',
                    fragment,
                    count=1,
                )
            sections.append(f'<div class="source-block">{fragment}</div>')
        return "\n".join(sections) + "\n"


def update_generated_assets(staging_dir: Path, rendered: str) -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    current_names = {
        path.name
        for path in staging_dir.iterdir()
        if path.is_file() and f"assets/generated/{path.name}" in rendered
    }
    for existing in GENERATED_DIR.iterdir():
        if existing.is_file() and existing.name not in current_names:
            existing.unlink()
    for staged in staging_dir.iterdir():
        if staged.name not in current_names:
            continue
        destination = GENERATED_DIR / staged.name
        if not destination.exists() or destination.read_bytes() != staged.read_bytes():
            shutil.copy2(staged, destination)


def main() -> None:
    page_bytes, _content_type = fetch(SOURCE_URL)
    with tempfile.TemporaryDirectory(prefix="yimin-homepage-") as temporary:
        staging_dir = Path(temporary)
        parser = GoogleSiteParser(staging_dir)
        parser.feed(page_bytes.decode("utf-8"))
        rendered = parser.render()
        if "Short Bio" not in rendered or "PAPER LIST" not in rendered:
            raise RuntimeError("Google Sites markup changed; refusing to replace known-good content")

        update_generated_assets(staging_dir, rendered)
        CONTENT_FILE.write_text(rendered, encoding="utf-8")
        state = {
            "source": SOURCE_URL,
            "content_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
            "blocks": rendered.count('class="source-block"'),
            "images": parser.image_index,
        }
        STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Synced {state['blocks']} content blocks and {state['images']} images")


if __name__ == "__main__":
    main()
