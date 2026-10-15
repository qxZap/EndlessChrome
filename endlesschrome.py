"""EndlessChrome: run and manage many isolated Chromium profiles from one web dashboard.

python endlesschrome.py              dashboard on http://localhost:8790
python endlesschrome.py --selftest

Env: ENDLESS_PORT (8790), ENDLESS_DATA (./data), ENDLESS_TZ (e.g. Europe/Berlin),
     ENDLESS_USER (endless) + ENDLESS_PASSWORD turn on a login; ENDLESS_BIND + ENDLESS_PASSWORD to reach it from other devices (password required then).
"""
import base64, html, json, os, random, re, secrets, shutil, socket, subprocess, sys, threading, time, uuid
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DIR = Path(__file__).resolve().parent
if (DIR / ".env").exists():  # KEY=VALUE lines; real environment variables win
    for line in (DIR / ".env").read_text("utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.strip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
DATA = Path(os.environ.get("ENDLESS_DATA", DIR / "data")).resolve()
PROFILES, SHARED = DATA / "profiles", DATA / "shared"
KINDS = {  # what a profile runs: same Selkies viewer, /config home and SUBFOLDER support in both images
    "browser": os.environ.get("ENDLESS_IMAGE", "lscr.io/linuxserver/chromium:latest"),
    "os": os.environ.get("ENDLESS_OS_IMAGE", "lscr.io/linuxserver/webtop:ubuntu-xfce"),
}
PORT = int(os.environ.get("ENDLESS_PORT", 8790))
BIND = os.environ.get("ENDLESS_BIND", "127.0.0.1")
LOCAL = BIND in ("127.0.0.1", "localhost")
USER = os.environ.get("ENDLESS_USER", "endless")
PASSWORD = os.environ.get("ENDLESS_PASSWORD", "")
FIRST_PORT = 23100
FOLDERS = ("Downloads", "Documents", "Shared")
ICON_SIZES = ("48", "192", "512")  # favicon, app icon, splash/store icon
PALETTE = ["#4f7cff", "#ff6b4f", "#22b07d", "#b55cff", "#ffb020", "#ff4f9a", "#14a8c4", "#7a8b99"]
lock = threading.Lock()


# ---------- profiles (profile.json is the source of truth, docker only says what runs) ----------

def load(pid):
    return json.loads((PROFILES / pid / "profile.json").read_text("utf-8"))


def save(p):
    (PROFILES / p["id"] / "profile.json").write_text(json.dumps(p, indent=2), "utf-8")


def all_profiles():
    if not PROFILES.exists():
        return []
    ps = [load(d.name) for d in PROFILES.iterdir() if (d / "profile.json").exists()]
    return sorted(ps, key=lambda p: p["created"])


def docker(*args, timeout=900):
    r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or f"docker {args[0]} failed")
    return r.stdout


def running_ids():
    out = docker("ps", "--filter", "label=endlesschrome", "--format", '{{.Label "endlesschrome"}}', timeout=30)
    return set(out.split())


def port_free(port):
    for host in ("127.0.0.1", "0.0.0.0"):
        with socket.socket() as s:
            try:
                s.bind((host, port))
            except OSError:
                return False  # in use, or reserved (Windows/Hyper-V reserves whole ranges)
    return True


def alloc_ports(n):
    used = {v for p in all_profiles() for v in p["ports"].values()}
    out, port = [], FIRST_PORT
    while len(out) < n:
        if port not in used and port_free(port):
            out.append(port)
        port += 1
    return out


def image_of(p):
    return KINDS[p.get("kind", "browser")]


def in_image(image, script, *mounts):
    """Run a shell line in the profile's image, so Linux owners/symlinks inside profiles are handled on any host."""
    vols = [a for host, ctr in mounts for a in ("-v", f"{host}:{ctr}")]
    docker("run", "--rm", *vols, "--entrypoint", "sh", image, "-c", script)


def start(pid):
    p, home = load(pid), PROFILES / pid / "home"
    pr = p["ports"]
    args = ["run", "-d", "--rm", "--name", f"endless-{pid}", "--label", f"endlesschrome={pid}",
            "--shm-size=1g", "--hostname", re.sub(r"[^a-z0-9-]", "", p["name"].lower().replace(" ", "-"))[:40] or pid,
            "-p", f"127.0.0.1:{pr['view']}:3000",
            "-v", f"{home}:/config", "-v", f"{SHARED}:/config/Shared",
            "-e", f"TITLE={p['name']}", "-e", f"SUBFOLDER=/v/{pid}/"]  # the dashboard proxies the viewer at this path
    if p.get("kind", "browser") == "browser":
        args += ["-p", f"127.0.0.1:{pr['cdp']}:9223",
                 "-v", f"{DIR / 'cdp-forward'}:/custom-services.d/cdp-forward:ro",
                 "-e", "CHROME_CLI=--remote-debugging-port=9222 --hide-crash-restore-bubble"]
        if (DIR / "policies").is_dir():
            args += ["-v", f"{DIR / 'policies'}:/etc/chromium/policies/managed:ro"]
    if os.environ.get("ENDLESS_TZ"):
        args += ["-e", f"TZ={os.environ['ENDLESS_TZ']}"]
    if hasattr(os, "getuid"):
        args += ["-e", f"PUID={os.getuid()}", "-e", f"PGID={os.getgid()}"]
    docker(*args, image_of(p))


def stop(pid):
    if pid in running_ids():
        # close Chromium itself first: a container stop kills it before cookies/localStorage reach disk
        docker("exec", f"endless-{pid}", "sh", "-c",
               "pkill -TERM -o chromium; for i in $(seq 20); do pgrep -x chromium >/dev/null || break; sleep .5; done",
               timeout=30)
        docker("stop", "-t", "10", f"endless-{pid}", timeout=60)  # --rm removes it


def create(name, color=None, clone_of=None, kind="browser"):
    with lock:
        pid = uuid.uuid4().hex[:8]
        view, cdp = alloc_ports(2)
        root = PROFILES / pid
        (root / "home").mkdir(parents=True)
        SHARED.mkdir(parents=True, exist_ok=True)
        p = {"id": pid, "name": name, "color": color or random.choice(PALETTE), "created": time.time(),
             "ports": {"view": view, "cdp": cdp}, "kind": kind}
        if clone_of:
            src = load(clone_of)
            p["kind"] = src.get("kind", "browser")
            if src.get("icon"):
                for s in ICON_SIZES:
                    shutil.copy(PROFILES / clone_of / f"icon-{s}.png", root / f"icon-{s}.png")
                p["icon"] = src["icon"]
            was_running = clone_of in running_ids()
            stop(clone_of)  # copy a closed profile, not one Chromium is writing to
            try:
                in_image(image_of(src), "cp -a /src/. /dst/ && rm -f /dst/.config/chromium/Singleton*",
                         (PROFILES / clone_of / "home", "/src"), (root / "home", "/dst"))
            finally:
                if was_running:
                    start(clone_of)
        else:
            for f in FOLDERS[:2]:
                (root / "home" / f).mkdir()
        save(p)
    start(pid)
    return p


def delete(pid):
    stop(pid)
    in_image(image_of(load(pid)), "rm -rf /p/home", (PROFILES / pid, "/p"))
    shutil.rmtree(PROFILES / pid)


def ready(p):
    try:
        return urllib.request.urlopen(f"http://127.0.0.1:{p['ports']['view']}/v/{p['id']}/", timeout=2).status == 200
    except OSError:
        return False


def open_folder(pid, folder):
    path = SHARED if folder == "Shared" else PROFILES / pid / "home" / folder
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


# ---------- per-profile app (PWA) ----------

def initials(name):
    words = re.findall(r"\w+", name) or ["?"]
    return (words[0][0] + (words[1][0] if len(words) > 1 else words[0][1:2])).upper()


def icon_svg(p):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">'
            f'<rect width="512" height="512" rx="112" fill="{html.escape(p["color"])}"/>'
            f'<text x="256" y="256" dy=".35em" text-anchor="middle" font-family="Segoe UI,Helvetica,Arial,sans-serif" '
            f'font-weight="700" font-size="220" fill="#fff">{html.escape(initials(p["name"]))}</text></svg>')


def icon_url(p, size):
    return f"/p/{p['id']}/icon-{size}.png?v={p['icon']}" if p.get("icon") else f"/p/{p['id']}/icon.svg"


def valid_png(data):
    return data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) < 3_000_000


def set_icon(pid, pngs):
    """pngs: {"48"|"192"|"512": base64 PNG}, already resized by the dashboard."""
    files = {s: base64.b64decode(pngs.get(s, ""), validate=True) for s in ICON_SIZES}
    if not all(map(valid_png, files.values())):
        raise ValueError("icon must be PNGs at 48, 192 and 512 px")
    for s, data in files.items():
        (PROFILES / pid / f"icon-{s}.png").write_bytes(data)
    p = load(pid)
    p["icon"] = int(time.time())
    save(p)
    return p


def clear_icon(pid):
    for s in ICON_SIZES:
        (PROFILES / pid / f"icon-{s}.png").unlink(missing_ok=True)
    p = load(pid)
    p.pop("icon", None)
    save(p)
    return p


def manifest(p):
    base = f"/p/{p['id']}/"
    icons = ([{"src": icon_url(p, s), "sizes": f"{s}x{s}", "type": "image/png", "purpose": "any"} for s in ("192", "512")]
             if p.get("icon") else [{"src": "icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}])
    return {"id": base, "name": p["name"], "short_name": p["name"][:12], "start_url": base, "scope": base,
            "display": "standalone", "background_color": "#0e0f13", "theme_color": p["color"], "icons": icons}


# ---------- HTTP ----------

def host_ok(host_header):
    # with a password set, any host (e.g. an ngrok URL) is fine: the login is what protects it
    return bool(PASSWORD) or not LOCAL or host_header.rsplit(":", 1)[0] in ("localhost", "127.0.0.1", "[::1]")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body=b"", ctype="application/json"):
        if not isinstance(body, bytes):
            body = (body if isinstance(body, str) else json.dumps(body)).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def guard(self, csrf=True):
        if not host_ok(self.headers.get("Host", "")):  # blocks DNS-rebinding sites from driving docker
            self.send(403, {"error": "bad host"})
            return False
        if PASSWORD:
            want = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
            if not secrets.compare_digest(self.headers.get("Authorization", ""), want):
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="EndlessChrome"')
                self.end_headers()
                return False
        # custom header forces a CORS preflight we never answer, so other sites can't POST here
        if csrf and self.command != "GET" and self.headers.get("X-EndlessChrome") != "1":
            self.send(403, {"error": "missing X-EndlessChrome header"})
            return False
        return True

    def proxy(self):
        """Relay /v/<id>/... (plain HTTP and the viewer's websocket) to that profile's container."""
        if not self.guard(csrf=False):
            return
        m = re.match(r"/v/(\w+)/", self.path)
        if not m or not (PROFILES / m[1] / "profile.json").exists():
            return self.send(404, {"error": "not found"})
        try:
            up = socket.create_connection(("127.0.0.1", load(m[1])["ports"]["view"]), timeout=10)
        except OSError:
            return self.send(502, {"error": "profile is not running"})
        upgrade = self.headers.get("Upgrade", "").lower() == "websocket"
        head = [f"{self.command} {self.path} HTTP/1.1"] + [
            f"{k}: {v}" for k, v in self.headers.items() if k.lower() not in ("connection", "keep-alive", "authorization")]
        # one request per upstream connection, so a reused browser connection can't skip this handler
        head.append("Connection: Upgrade" if upgrade else "Connection: close")
        up.sendall(("\r\n".join(head) + "\r\n\r\n").encode("latin-1"))
        up.settimeout(None)
        self.close_connection = True

        def client_to_container():
            try:
                while data := self.rfile.read1(65536):
                    up.sendall(data)
            except OSError:
                pass

        threading.Thread(target=client_to_container, daemon=True).start()
        try:
            while data := up.recv(65536):
                self.connection.sendall(data)
        except OSError:
            pass
        finally:
            up.close()

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path.startswith("/v/"):
            return self.proxy()
        if not self.guard():
            return
        path = self.path.split("?")[0]
        if path == "/":
            return self.send(200, (DIR / "static" / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/profiles":
            run = running_ids()
            return self.send(200, {"local": LOCAL, "profiles": [{**p, "running": p["id"] in run} for p in all_profiles()]})
        m = re.fullmatch(r"/api/profiles/(\w+)", path)
        if m and (PROFILES / m[1] / "profile.json").exists():
            p = load(m[1])
            return self.send(200, {**p, "local": LOCAL, "running": m[1] in running_ids(), "ready": ready(p)})
        m = re.fullmatch(r"/p/(\w+)/(|manifest\.webmanifest|icon\.svg|icon-(48|192|512)\.png)", path)
        if m and (PROFILES / m[1] / "profile.json").exists():
            p = load(m[1])
            if m[3]:
                f = PROFILES / m[1] / f"icon-{m[3]}.png"
                return self.send(200, f.read_bytes(), "image/png") if f.exists() else self.send(404, {"error": "no icon"})
            if m[2] == "icon.svg":
                return self.send(200, icon_svg(p), "image/svg+xml")
            if m[2]:
                return self.send(200, manifest(p), "application/manifest+json")
            page = (DIR / "static" / "app.html").read_text("utf-8")
            for k, v in {"ID": p["id"], "NAME": p["name"], "COLOR": p["color"],
                         "ICON": icon_url(p, "192"), "FAVICON": icon_url(p, "48")}.items():
                page = page.replace("{{%s}}" % k, html.escape(v))
            return self.send(200, page, "text/html; charset=utf-8")
        self.send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.startswith("/v/"):
            return self.proxy()
        if not self.guard():
            return
        try:
            if self.path == "/api/profiles":
                b = self.body()
                name = str(b.get("name", "")).strip()[:60]
                if not name:
                    return self.send(400, {"error": "name required"})
                clone_of = b.get("clone_of")
                if clone_of and not (PROFILES / str(clone_of) / "profile.json").exists():
                    return self.send(404, {"error": "no such profile"})
                kind = b.get("kind", "browser")
                if kind not in KINDS:
                    return self.send(400, {"error": "kind must be browser or os"})
                color = b.get("color") if re.fullmatch(r"#[0-9a-fA-F]{6}", str(b.get("color", ""))) else None
                return self.send(201, create(name, color, clone_of, kind))
            m = re.fullmatch(r"/api/profiles/(\w+)/icon", self.path)
            if m and (PROFILES / m[1] / "profile.json").exists():
                try:
                    return self.send(200, set_icon(m[1], self.body()))
                except ValueError as e:  # binascii.Error is a ValueError too
                    return self.send(400, {"error": str(e)})
            m = re.fullmatch(r"/api/profiles/(\w+)/(start|stop|folder/(\w+))", self.path)
            if not m or not (PROFILES / m[1] / "profile.json").exists():
                return self.send(404, {"error": "not found"})
            if m[2] == "start":
                if m[1] not in running_ids():
                    start(m[1])
            elif m[2] == "stop":
                stop(m[1])
            elif m[3] in FOLDERS:
                open_folder(m[1], m[3])
            else:
                return self.send(404, {"error": "unknown folder"})
            self.send(200, {"ok": True})
        except Exception as e:
            self.send(500, {"error": str(e)})

    def do_PATCH(self):
        if self.path.startswith("/v/"):
            return self.proxy()
        if not self.guard():
            return
        m = re.fullmatch(r"/api/profiles/(\w+)", self.path)
        if not m or not (PROFILES / m[1] / "profile.json").exists():
            return self.send(404, {"error": "not found"})
        b, p = self.body(), load(m[1])
        if str(b.get("name", "")).strip():
            p["name"] = str(b["name"]).strip()[:60]
        if re.fullmatch(r"#[0-9a-fA-F]{6}", str(b.get("color", ""))):
            p["color"] = b["color"]
        save(p)
        self.send(200, p)

    def do_DELETE(self):
        if self.path.startswith("/v/"):
            return self.proxy()
        if not self.guard():
            return
        m = re.fullmatch(r"/api/profiles/(\w+)(/icon)?", self.path)
        if not m or not (PROFILES / m[1] / "profile.json").exists():
            return self.send(404, {"error": "not found"})
        if m[2]:
            return self.send(200, clear_icon(m[1]))
        try:
            delete(m[1])
            self.send(200, {"ok": True})
        except Exception as e:
            self.send(500, {"error": str(e)})


def selftest():
    global LOCAL
    assert initials("Work Account") == "WA" and initials("ig") == "IG" and initials("!!") == "?"
    p = {"id": "abc", "name": "<x> & y", "color": '"/><script>'}
    assert "<script>" not in icon_svg(p)  # color/name can't inject markup
    m = manifest(p)
    assert m["scope"] == m["start_url"] == m["id"] == "/p/abc/"
    assert manifest({**p, "icon": 7})["icons"][1]["src"] == "/p/abc/icon-512.png?v=7"
    assert valid_png(b"\x89PNG\r\n\x1a\n...") and not valid_png(b"<svg onload=x>")
    LOCAL = True
    assert host_ok("localhost:8790") and host_ok("127.0.0.1:8790") and not host_ok("evil.com:8790")
    a = alloc_ports(3)
    assert len(set(a)) == 3 and all(port_free(x) for x in a)
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
    else:
        if not LOCAL and not PASSWORD:
            sys.exit("ENDLESS_BIND exposes the dashboard to other devices: set ENDLESS_PASSWORD too.")
        PROFILES.mkdir(parents=True, exist_ok=True)
        SHARED.mkdir(parents=True, exist_ok=True)
        print(f"EndlessChrome on http://{'localhost' if LOCAL else BIND}:{PORT}")
        ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
