# Yimin Tang — complete homepage mirror

Public entry: <https://tachikakamin.github.io/yimintang-homepage/>

This repository mirrors the current personal homepage and both complete public
interactive demo sites. Google Sites currently embeds the homepage; the mirror
copies the embedded website itself, including its JavaScript, styles, images,
scene pages, recorded solver trajectories, and technical reports.

| Source | Local destination |
| --- | --- |
| `yimin-tang.gain-salvo-0t.chatgpt.site` | `/` |
| `multi-robot-construction-demo.gain-salvo-0t.chatgpt.site` | `/interactive/construction/` |
| `lacam-autostore-demo.gain-salvo-0t.chatgpt.site` | `/interactive/autostore/` |

Homepage previews remain in `demos/`. Their full-demo buttons open the local
interactive sites. Links between these sites use relative paths, so they work
under GitHub Pages' `/yimintang-homepage/` prefix and on a custom domain.

## Synchronization and deployment

`.github/workflows/sync-google-site.yml` runs daily at 08:17 UTC, on pushes to
`main`, and through **Actions → Sync Google Site → Run workflow**. GitHub may
start scheduled runs later than the requested time.

The workflow tests the synchronizer, downloads public files and their
HTML/CSS/JavaScript dependencies, validates links, commits changed files, then
explicitly deploys the validated snapshot to GitHub Pages. Pages uses the
**GitHub Actions** publishing source. Explicit deployment is required because
[pushes made with `GITHUB_TOKEN` do not trigger another workflow](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).

The workflow builds in a temporary directory. A missing page, missing local
asset, challenge response, or external runtime resource fails validation before
replacing the existing mirror. Only files managed by the previous manifest may
be removed. No private Sites or source credentials are stored here.

`mirror-config.json` records the three public origins, mount points, initial
file inventory, and public Drive attachments. The crawler also discovers linked
pages, styles, scripts, fetched data, and demo scene navigation. If a source
moves to a different domain, update its URL in this configuration. New unlinked
files need to be added to its `files` list.

`sync-state.json` records SHA-256 hashes, source origins, page count, total size,
attachment freshness, and validation results. `sync-trace.json` records the
source URL and download method for every mirrored website file.

Run locally:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/sync_google_site.py
python3 -m http.server 8080
```

Open <http://localhost:8080/>. Python 3.12+ and `curl` are required; no Python
packages or browser runtime CDNs are needed. A local source checkout can seed
an initial import with `--source-dir name=/absolute/public/directory`.

## Media and external links

The CV, two slide decks, and public Drive project video are hosted in this
repository and refreshed on synchronization. If Drive is temporarily unavailable,
the last local attachment is retained and marked `cached` in the manifest.

YouTube embeds use locally hosted posters and retain outbound watch links.
YouTube playback and the NotebookLM podcast remain external; their media are
not copied by this mirror. Paper pages, code repositories, and other third-party
links remain outbound. Reading the homepage and playing the local robot demos
does not require Google, ChatGPT Sites, or a third-party JavaScript CDN.

## Additional hosting

The same repository can be connected to Tencent EdgeOne Pages. Use **Other**
as the framework, no build command, output directory `.`, and branch `main`.
The existing `edgeone.json` supplies response headers. A custom domain can
provide an additional public entry.

Removing Google runtime dependencies does not guarantee that GitHub Pages is
reachable from every mainland network. This task does not provision a mainland
hosting account or domain.

## Browser verification

[Recorded browser checks](validation/browser-results.json) exercise both local
homepage previews; AutoStore pause, single-step, final-state and timeline seek;
and construction playback, timeline seek and switching among 16 scenes. The
checks run under the project URL prefix with all external requests blocked.
