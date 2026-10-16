# AGENTS.md

Notes for AI coding agents working on EndlessChrome. Read README.md first for what the product does.

## Layout

- `endlesschrome.py`: the whole backend. Stdlib-only HTTP server plus `docker` CLI calls. Keep it dependency-free.
- `static/index.html`: the dashboard. Vanilla JS, no build step.
- `static/app.html`: the per-profile app (PWA) page, a template filled with `{{ID}}`, `{{NAME}}` and `{{COLOR}}`.
- Viewer relay: `Handler.proxy()` forwards `/v/<id>/...` (HTTP + websocket) to the container, which runs with
  `SUBFOLDER=/v/<id>/`. Keep it behind `guard()`; it skips only the CSRF header check, since the viewer posts its own requests.
- `cdp-forward`: Python service mounted at `/custom-services.d/` in each container. It exposes Chromium's DevTools port
  (bound to 127.0.0.1 inside the container) on `0.0.0.0:9223`.
- `policies/`: Chromium managed policies mounted into every container (uBlock Origin Lite force-install).
- `data/`: user data, gitignored. Never commit it, and never delete it in tests.

## Rules that matter

- Android profiles (`kind: android`) run budtmo/docker-android with `--device /dev/kvm`; their disks live in the docker volumes from
  `android_volumes()` (chowned to uid 1300 by `android_prepare()`), and noVNC is served from `/`, so `proxy()` strips `/v/<id>`.
- `proxy()` forces `Connection: close` on plain responses: a reused browser connection would bypass routing and `guard()`.
- Box passwords: PBKDF2 hash in `data/profiles/<id>/password.json` (never in profile.json, which API responses return raw).
  `box_ok()` guards `/p/<id>/` and the `/v/<id>/` relay; unlock sets an HMAC cookie tied to the stored hash, so a password
  change revokes it. Setting a password requires `local_request()` (loopback, local Host, no proxy headers) — keep that check.
- Profiles have a `kind` (`browser` default, `os`, or `android`). Chromium-only bits (CDP port, `cdp-forward`, `policies/`, `CHROME_CLI`)
  are applied only to browsers; `image_of(p)` picks the image.
- `static/app.html` watches the iframe for Selkies' "Connection Terminated" text to show the disconnected screen; `?watch` loads
  Selkies' read-only `#shared` mode.
- `profile.json` is the source of truth for profiles; Docker only tells us which ones are running
  (label `endlesschrome=<id>`). Containers run with `--rm`, so start always means a fresh container.
- **Stop Chromium before stopping the container** (`stop()` does this). Otherwise cookies and localStorage are lost,
  which corrupts clones.
- Clone and delete run file operations **inside the browser image** (`in_image`) so container-owned files and
  Linux symlinks work on every host OS. Don't swap this for `shutil` on profile homes.
- On Windows, Hyper-V reserves port ranges. Always allocate ports with `alloc_ports()`; it test-binds each port.
- Security: every non-GET request needs the `X-EndlessChrome: 1` header (CSRF), the Host header is checked in local mode
  (DNS rebinding), and any non-localhost bind requires `ENDLESS_PASSWORD`. Keep all three.
- Profile names and colours reach HTML, SVG and the manifest. Escape them, and validate colours as `#rrggbb`.

## Testing

- `python endlesschrome.py --selftest` covers the pure logic and must pass.
- End to end: run the server, then create, clone, rename, stop/start and delete through the API with the
  `X-EndlessChrome: 1` header. Check that a value written to localStorage survives a clone, and that a file
  downloaded in the browser appears in `data/profiles/<id>/home/Downloads`.
- The first container start pulls the image (~1 GB); allow several minutes for that.
