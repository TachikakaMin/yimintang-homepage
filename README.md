# Yimin Tang — original-layout homepage mirror

A static snapshot of the public Google Sites homepage that preserves its
original layout. Images, fonts, stylesheets, the CV, slides, and the hosted
project video are downloaded into this repository, so rendering the page does
not depend on Google-hosted runtime assets.

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
public page, removes Google Sites' runtime scripts, rewrites the original HTML
to local assets, and commits only when the snapshot changes. A push then
triggers GitHub Pages and any connected EdgeOne deployment.

Run the same synchronization locally:

```sh
python3 scripts/sync_google_site.py
python3 -m http.server 8080
```

Then open <http://localhost:8080>.

## Accessibility notes for visitors in China

The page itself has no Google runtime dependency. YouTube embeds are shown as
locally hosted posters that link to YouTube; those outbound links and other
external Google properties may still be unavailable on some networks.
