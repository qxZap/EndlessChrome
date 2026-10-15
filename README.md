# EndlessChrome

Run as many isolated Chromium browsers and full Linux desktops as your machine can hold, and manage them all from one web dashboard.

Each **profile** is its own Chromium in a lightweight Docker container (~400 MB RAM) with its own logins,
cookies, extensions and history. Every profile installs as its **own app**, with its own name, colour
and icon in your taskbar or dock.

<!-- Launch video goes here once v1 is validated. -->

## Features

- **Two kinds of profile:** *Browser* (one Chromium, ~400 MB) or *Full OS* (an Ubuntu XFCE desktop with `apt`, ~300 MB idle).
  Think of a Full OS profile as a Linux VM that starts in seconds.
- **Watch together:** *Copy watch link* in the ⚙ menu gives a read-only live view. Any number of people can watch while one person controls.
- **Create, clone, rename, recolour, start, stop and delete** profiles from the dashboard (the ⚙ menu on each card).
- **Custom icons:** upload any image. It is cropped square and converted in your browser to a 48 px favicon and 192/512 px app icons. Without an image, a letter icon in the profile colour is generated.
- **One app per profile:** open a profile and install it from Chrome's address bar. It gets its own window and icon.
- **Real folders on your disk:** each profile's `Downloads` and `Documents` are ordinary folders on your computer,
  and a `Shared` folder is mounted into every profile.
- **Ad blocking:** uBlock Origin Lite is force-installed in every profile. Delete `policies/` to turn it off.
- **Automation-ready:** each profile exposes Chrome DevTools Protocol on `127.0.0.1` for Playwright or Puppeteer.
- **No build step, no dependencies:** one Python file using only the standard library, plus Docker.

## Quick start

Requirements: Docker (Docker Desktop on Windows/macOS) and Python 3.9+.

```sh
git clone https://github.com/qxZap/EndlessChrome && cd EndlessChrome
python endlesschrome.py
```

Open <http://localhost:8790> and click **+ New profile**. The first profile downloads the browser image (about 1 GB);
after that a new profile starts in a few seconds.

To install a profile as an app, click **Open**, then click the install icon in Chrome's address bar.

## Where things live

```
data/
  profiles/<id>/profile.json     name, colour, ports
  profiles/<id>/home/            the browser's whole home folder
  profiles/<id>/home/Downloads/  downloads land here
  profiles/<id>/home/Documents/
  shared/                        mounted in every profile as ~/Shared
```

Back up `data/` and you've backed up every profile.

## Configuration

| Env var | Default | What it does |
|---|---|---|
| `ENDLESS_PORT` | `8790` | Dashboard port |
| `ENDLESS_DATA` | `./data` | Where profiles are stored |
| `ENDLESS_TZ` | container default (UTC) | Time zone the browsers report, e.g. `Europe/Berlin` |
| `ENDLESS_BIND` | `127.0.0.1` | Set to `0.0.0.0` to reach the dashboard from other devices |
| `ENDLESS_USER` | `endless` | Login username |
| `ENDLESS_PASSWORD` | — | Turns on a login for everything. Required when `ENDLESS_BIND` isn't localhost |
| `ENDLESS_IMAGE` | `lscr.io/linuxserver/chromium:latest` | Image for *Browser* profiles |
| `ENDLESS_OS_IMAGE` | `lscr.io/linuxserver/webtop:ubuntu-xfce` | Image for *Full OS* profiles (any linuxserver webtop tag works, e.g. `ubuntu-kde`) |

## Using it from anywhere

Everything (the dashboard, each profile's app and its live browser) is served from the one dashboard port. Profile views
are relayed under `/v/<id>/`. So one HTTPS tunnel is enough:

```sh
ENDLESS_PASSWORD='a-long-random-password' python endlesschrome.py
ngrok http 8790            # or: cloudflared tunnel --url http://localhost:8790, or Tailscale Funnel
```

Open the tunnel URL and log in with your `ENDLESS_USER` and password. **Always set a password before tunnelling:** the dashboard controls Docker
and your logged-in browsers. The browser stream needs HTTPS (or localhost), so plain `http://` over a LAN won't stream.
Use a tunnel or Tailscale instead.

## Automation

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:<cdp port from profile.json>")
    page = browser.contexts[0].pages[0]
```

`browser.close()` only disconnects; the profile keeps running.

## Known limits

- **One controller per profile at a time** (a limit of the Selkies streamer). If someone else opens the same profile to control it,
  the previous controller sees a *You were disconnected* screen and can take control back or watch instead.
  Watch links never disconnect anyone. Anyone with the dashboard login can control, so share the login only with people you trust.
- On Linux hosts, `cdp-forward` must be owned by root for the container to run it (`sudo chown root cdp-forward`).

## How it works

`endlesschrome.py` serves the dashboard and drives the `docker` CLI. Every profile is a
[linuxserver/chromium](https://docs.linuxserver.io/images/docker-chromium/) container, streamed to your browser with Selkies.
The dashboard relays each container's viewer (HTTP and its websocket stream) at `/v/<id>/`, behind the same login.
`cdp-forward` is a tiny service inside each container that exposes Chromium's debugging port, which Chromium otherwise binds
to the container's own localhost. Profiles are stopped by closing Chromium first, so cookies are on disk before cloning or deleting.

```sh
python endlesschrome.py --selftest
```

## License

[MIT](LICENSE)
