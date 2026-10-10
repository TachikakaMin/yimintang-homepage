#!/usr/bin/env python3
"""Mirror the public homepage and complete public demo sites, preserving JS.

Build and validate in a temporary directory before modifying tracked files.
Only previously managed files may be removed; unrelated repository files remain.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urljoin, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'mirror-config.json').read_text())
PAGES_URL = 'https://tachikakamin.github.io/yimintang-homepage/'
TEXT_SUFFIXES = {'.html', '.css', '.js', '.json', '.svg', '.txt', '.md', '.ldr'}
ATTR = re.compile(r'''\b(href|src|poster|data-src)\s*=\s*(["'])(.*?)\2''', re.I | re.S)
CSS_URL = re.compile(r'''url\(\s*(["']?)([^)'"\s]+)\1\s*\)''', re.I)
CSS_IMPORT = re.compile(r'''@import\s+["']([^"']+)["']''', re.I)
# Actual JS file loads and the SCENES navigation array; PAGE_EN keys are not links.
JS_LOAD = re.compile(r'''(?:fetch\(|import\s*\(|from\s+|import\s+)[\s]*["']([^"']+)["']''')
SCENES = re.compile(r'const\s+SCENES\s*=\s*\[(.*?)\];', re.S)
SCENE_LINK = re.compile(r'''\[\s*["']([^"']+\.html)["']''')
ROOT_FILE = re.compile(r'''(["'])(/[^"'\s]+\.(?:html|js|css|json|png|jpg|svg)(?:\?[^"']*)?)\1''')
# Cloudflare injects this at the edge; it is not application source.
CF_SCRIPT = re.compile(r'<script\b[^>]*>[^<]*__CF\$cv\$params.*?</script>', re.S)


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
    def handle_starttag(self, tag, attributes):
        for name, value in attributes:
            if value and name in {'href', 'src', 'poster', 'data-src'}:
                self.urls.append(value)
            if value and name == 'srcset':
                self.urls.extend(part.strip().split()[0] for part in value.split(','))


def references(text, suffix):
    urls = []
    if suffix == '.html':
        parser = References()
        parser.feed(text)
        urls.extend(parser.urls)
    if suffix in {'.css', '.html'}:
        urls.extend(m.group(2) for m in CSS_URL.finditer(text))
        urls.extend(m.group(1) for m in CSS_IMPORT.finditer(text))
    if suffix in {'.js', '.html'}:
        urls.extend(m.group(1) for m in JS_LOAD.finditer(text))
        for block in SCENES.finditer(text):
            urls.extend(m.group(1) for m in SCENE_LINK.finditer(block.group(1)))
    return urls


def safe_path(value):
    value = value.lstrip('/')
    if not value or any(p in {'.', '..'} for p in PurePosixPath(value).parts) or '\\' in value:
        raise ValueError(f'Unsafe mirror path: {value}')
    if value.split('/')[0] in {'.git', '.github', 'scripts', '.openai'}:
        raise ValueError(f'Reserved mirror path: {value}')
    return value


def fetch(url):
    # curl also works with macOS TLS and Sites' public edge. No credentials.
    result = subprocess.run([
        'curl', '--fail', '--silent', '--show-error', '--location',
        '--retry', '3', '--retry-delay', '1', '--max-time', '120',
        '--user-agent', 'Mozilla/5.0 (compatible; YiminHomepageMirror/2.0)', url,
    ], capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f'Download failed: {url}: {result.stderr.decode(errors="replace").strip()}')
    if not result.stdout:
        raise RuntimeError(f'Empty response: {url}')
    return result.stdout


class Mirror:
    def __init__(self, staging, source_dirs=None):
        self.staging = staging
        self.source_dirs = source_dirs or {}
        self.sources = CONFIG['sources']
        self.files = {}
        self.trace = []
        self.document_status = []

    def resolve(self, url, base):
        absolute = urlsplit(urljoin(base, html.unescape(url)))
        if absolute.scheme not in {'http', 'https'}:
            return None
        for source in self.sources:
            origin = urlsplit(source['url'])
            if absolute.netloc != origin.netloc:
                continue
            relative = absolute.path.lstrip('/')
            if not relative or relative.endswith('/'):
                relative += 'index.html'
            relative = safe_path(relative)
            destination = safe_path(posixpath.join(source['mount'], relative))
            clean_url = urlunsplit((absolute.scheme, absolute.netloc, absolute.path, '', ''))
            return source, relative, destination, clean_url, absolute.query, absolute.fragment
        return None

    def local_url(self, url, base, destination):
        if url.startswith(('#', '?')):
            return url
        resolved = self.resolve(url, base)
        if not resolved:
            return url
        _source, _relative, target, _clean, query, fragment = resolved
        local = posixpath.relpath(target, posixpath.dirname(destination) or '.')
        return local + ('?' + query if query else '') + ('#' + fragment if fragment else '')

    def load(self, source, relative, destination, url):
        if source['name'] in self.source_dirs:
            path = Path(self.source_dirs[source['name']]) / relative
            # construction sources are buildless except Vite's entry HTML.
            if not path.exists() and source['name'] == 'construction' and relative == 'index.html':
                path = path.parent.parent / 'index.html'
            if path.exists():
                return path.read_bytes(), 'source-checkout'
        try:
            return fetch(url), 'public-site'
        except RuntimeError:
            # The homepage ships preview subsets. Missing navigation targets
            # belong to its complete public demo sites, not a Google runtime.
            for prefix, name, remote_prefix in [
                ('demos/construction/', 'construction', 'scenes/'),
                ('demos/autostore/', 'autostore', ''),
            ]:
                if source['name'] == 'homepage' and relative.startswith(prefix):
                    sibling = next(s for s in self.sources if s['name'] == name)
                    sibling_relative = remote_prefix + relative[len(prefix):]
                    if name in self.source_dirs:
                        local = Path(self.source_dirs[name]) / sibling_relative
                        if local.exists():
                            return local.read_bytes(), 'demo-navigation-source'
                    remote = urljoin(sibling['url'], sibling_relative)
                    return fetch(remote), 'demo-navigation-fallback'
            raise

    def download_all(self):
        pending = {}
        for source in self.sources:
            for relative in source['files']:
                destination = safe_path(posixpath.join(source['mount'], relative))
                pending[destination] = (source, relative, destination, urljoin(source['url'], relative))
        while pending:
            batch = sorted(pending.values(), key=lambda item: item[2])
            pending = {}
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda item: self.load(*item), batch))
            for item, (data, mode) in zip(batch, results):
                source, relative, destination, url = item
                suffix = Path(destination).suffix
                if suffix != '.html' and data.lstrip().lower().startswith((b'<!doctype html', b'<html')):
                    raise RuntimeError(f'Unexpected HTML instead of asset: {url}')
                if suffix in TEXT_SUFFIXES:
                    text = data.decode('utf-8')
                    if suffix == '.html':
                        text = CF_SCRIPT.sub('', text)
                        if 'Just a moment...' in text or 'cf-chl-' in text:
                            raise RuntimeError(f'Challenge page instead of website: {url}')
                    for ref in references(text, suffix):
                        resolved = self.resolve(ref, url)
                        if resolved and resolved[2] not in self.files:
                            pending.setdefault(resolved[2], resolved[:4])
                    # Preserve app code. Rewrite only known public Site origins
                    # and root-relative HTML/CSS URLs for project Pages paths.
                    text = ATTR.sub(lambda m: m.group(1) + '=' + m.group(2) +
                                    html.escape(self.local_url(m.group(3), url, destination), quote=True) + m.group(2), text) if suffix == '.html' else text
                    if suffix in {'.html', '.css'}:
                        text = CSS_URL.sub(lambda m: 'url(' + m.group(1) + self.local_url(m.group(2), url, destination) + m.group(1) + ')', text)
                        text = CSS_IMPORT.sub(lambda m: '@import "' + self.local_url(m.group(1), url, destination) + '"', text)
                    if suffix in {'.html', '.js'}:
                        text = ROOT_FILE.sub(lambda m: m.group(1) + self.local_url(m.group(2), url, destination) + m.group(1), text)
                    data = text.encode()
                self.files[destination] = data
                self.trace.append({'path': destination, 'source': url, 'method': mode})
            pending = {key: item for key, item in pending.items() if key not in self.files}
            if len(self.files) + len(pending) > 1000:
                raise RuntimeError('Unexpected crawl expansion; refusing to publish')
            print(f'Collected {len(self.files)} files; {len(pending)} dependencies pending', flush=True)

    def localize_documents(self):
        for file_id, specification in CONFIG['drive_files'].items():
            destination = specification['path']
            download = 'https://drive.usercontent.google.com/download?id=' + file_id + '&export=download&confirm=t'
            try:
                data = fetch(download)
                if specification['type'] == 'pdf' and not data.startswith(b'%PDF'):
                    raise RuntimeError('Drive returned non-PDF content')
                if specification['type'] == 'video' and not (len(data) > 12 and data[4:8] == b'ftyp'):
                    raise RuntimeError('Drive returned non-video content')
                status = 'refreshed'
            except RuntimeError as error:
                cached = ROOT / destination
                if not cached.exists():
                    raise
                data = cached.read_bytes()
                if specification['type'] == 'pdf' and not data.startswith(b'%PDF'):
                    raise RuntimeError(f'Invalid cached PDF: {destination}')
                status = 'cached'
                print(f'Using cached public attachment {destination}: {error}', flush=True)
            self.files[destination] = data
            self.document_status.append({'path': destination, 'status': status})
        drive_pattern = re.compile(r'https://drive\.google\.com/file/d/([^/?#]+)[^"\s<>]*')
        for destination, data in list(self.files.items()):
            if not destination.endswith('.html'):
                continue
            text = data.decode()
            def replace_drive(match):
                file_id = match.group(1)
                spec = CONFIG['drive_files'].get(file_id)
                return posixpath.relpath(spec['path'], posixpath.dirname(destination) or '.') if spec else match.group(0)
            # Drive video iframe becomes a native player backed by local media.
            def replace_frame(match):
                drive = drive_pattern.search(match.group(0))
                if not drive or drive.group(1) not in CONFIG['drive_files']:
                    return match.group(0)
                local = replace_drive(drive)
                return '<video controls preload="metadata" playsinline src="' + local + '" aria-label="Project video" style="width:100%;height:100%;object-fit:contain"></video>'
            text = re.sub(r'<iframe\b[^>]*>\s*</iframe>', replace_frame, text, flags=re.I)
            text = drive_pattern.sub(replace_drive, text)
            # YouTube stays explicitly outbound; the homepage loads no blocked
            # video iframe. Local posters preserve the visual and original link.
            def youtube_frame(match):
                video = re.search(r'https://www\.youtube(?:-nocookie)?\.com/embed/([^?"&/]+)', match.group(0))
                if not video:
                    return match.group(0)
                vid = video.group(1)
                poster = 'assets/video-posters/' + vid + '.jpg'
                if poster not in self.files:
                    self.files[poster] = fetch('https://i.ytimg.com/vi/' + vid + '/hqdefault.jpg')
                local = posixpath.relpath(poster, posixpath.dirname(destination) or '.')
                return '<a href="https://www.youtube.com/watch?v=' + vid + '" target="_blank" rel="noopener" aria-label="Watch video on YouTube" style="display:block;width:100%;height:100%"><img src="' + local + '" alt="Watch video on YouTube" loading="lazy" style="width:100%;height:100%;object-fit:cover"></a>'
            text = re.sub(r'<iframe\b[^>]*>\s*</iframe>', youtube_frame, text, flags=re.I)
            self.files[destination] = text.encode()

    def validate(self):
        missing = []
        external_runtime = []
        for destination, data in self.files.items():
            suffix = Path(destination).suffix
            if suffix not in {'.html', '.css', '.js'}:
                continue
            text = data.decode()
            for reference in references(text, suffix):
                parsed = urlsplit(html.unescape(reference))
                if suffix in {'.css', '.js'} and parsed.scheme in {'http', 'https'}:
                    external_runtime.append({'from': destination, 'url': reference})
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                target = posixpath.normpath(posixpath.join(posixpath.dirname(destination), parsed.path))
                if target.endswith('/') or parsed.path.endswith('/'):
                    target += '/index.html'
                if target not in self.files and target not in {'404.html', 'robots.txt'}:
                    missing.append({'from': destination, 'target': target})
            if suffix == '.html':
                for match in re.finditer(r'<(?:script|iframe|img|video|link)\b[^>]*>', text, re.I):
                    tag = match.group(0)
                    # stylesheet/preload/icon are runtime resources; canonical is metadata.
                    if tag.lower().startswith('<link') and not re.search(r'stylesheet|preload|icon', tag, re.I):
                        continue
                    for attr in ATTR.finditer(tag):
                        if urlsplit(attr.group(3)).scheme in {'http', 'https'}:
                            external_runtime.append({'from': destination, 'url': attr.group(3)})
        if missing:
            raise RuntimeError('Broken local links: ' + json.dumps(missing, ensure_ascii=False))
        if external_runtime:
            raise RuntimeError('External runtime dependencies: ' + json.dumps(external_runtime))
        if b'Robotics' not in self.files.get('index.html', b'') or b'motion-toggle' not in self.files['index.html']:
            raise RuntimeError('Unexpected homepage; refusing to replace known-good mirror')
        return {'missing_local_links': missing, 'external_runtime_dependencies': external_runtime}

    def publish(self):
        validation = self.validate()
        file_hashes = {p: hashlib.sha256(data).hexdigest() for p, data in sorted(self.files.items())}
        manifest = {'mode': 'complete-public-sites', 'sources': [{k: s[k] for k in ('name', 'url', 'mount')} for s in self.sources],
                    'files': file_hashes, 'validation': validation, 'attachments': self.document_status,
                    'html_pages': sum(p.endswith('.html') for p in self.files),
                    'total_bytes': sum(len(v) for v in self.files.values())}
        manifest['content_sha256'] = hashlib.sha256(json.dumps(file_hashes, sort_keys=True).encode()).hexdigest()
        for path, data in self.files.items():
            staged = self.staging / path
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(data)
        previous = json.loads((ROOT / 'sync-state.json').read_text()) if (ROOT / 'sync-state.json').exists() else {}
        # Stage/validate first. Never prune untracked repository content.
        for old in set(previous.get('files', {})) - set(self.files):
            (ROOT / safe_path(old)).unlink(missing_ok=True)
        for path in sorted(self.files):
            output = ROOT / path
            output.parent.mkdir(parents=True, exist_ok=True)
            os.replace(self.staging / path, output)
        (ROOT / '.nojekyll').touch()
        (ROOT / 'sync-state.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
        (ROOT / 'sync-trace.json').write_text(json.dumps(sorted(self.trace, key=lambda r: r['path']), indent=2) + '\n')
        print(f'Validated and published {len(self.files)} files, {manifest["html_pages"]} HTML pages, {manifest["total_bytes"]:,} bytes', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-dir', action='append', default=[], help='Initial import: name=/absolute/public/directory')
    args = parser.parse_args()
    source_dirs = dict(item.split('=', 1) for item in args.source_dir)
    with tempfile.TemporaryDirectory(prefix='yimin-full-mirror-') as temporary:
        mirror = Mirror(Path(temporary), source_dirs)
        mirror.download_all()
        mirror.localize_documents()
        mirror.publish()


if __name__ == '__main__':
    main()
