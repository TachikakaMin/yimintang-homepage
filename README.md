# Yimin Tang — China-accessible homepage mirror

A lightweight, responsive mirror of the public Google Sites homepage. The site
ships its own images, documents, CSS, and JavaScript, so rendering never depends
on Google-hosted assets.

## Deploy to Tencent EdgeOne Pages

[![Deploy with EdgeOne Pages](https://cdnstatic.tencentcs.com/edgeone/pages/deploy.svg)](https://console.cloud.tencent.com/edgeone/pages/new?repository-url=https%3A%2F%2Fgithub.com%2FTachikakaMin%2Fyimintang-homepage&project-name=yimintang-homepage&output-directory=.)

Use these settings if the console asks:

- Framework preset: Other
- Build command: leave empty
- Output directory: `.`
- Production branch: `main`
- Acceleration area: Global (excluding Chinese mainland) without an ICP filing;
  Chinese mainland or Global with Chinese mainland after the domain has an ICP filing

Bind a custom domain after deployment. EdgeOne's generated project/deployment
domains are preview-oriented; a custom domain is the stable public entry point.

## Content synchronization

GitHub Actions runs `scripts/sync_google_site.py` daily. The script fetches the
public page, preserves semantic text and links, downloads Google-hosted images
and public Drive PDFs into this repository, and commits only when the generated
output changes. A push then triggers EdgeOne's connected-repository deployment.

Run the same synchronization locally:

```sh
python3 scripts/sync_google_site.py
python3 -m http.server 8080
```

Then open <http://localhost:8080>.

## Accessibility notes for visitors in China

The page itself has no Google runtime dependency. Links to YouTube, Google
Calendar, NotebookLM, and other external Google properties remain clearly
marked outbound links and may still be unavailable in some networks. Videos
should be uploaded to an accessible provider separately if in-page playback is
required.
