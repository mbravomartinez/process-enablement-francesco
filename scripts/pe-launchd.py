#!/usr/bin/env python3
"""
pe-launchd.py — the one thing on this machine that is allowed to start a chat bridge.

Why it exists: an exploration page is a `file://` document, so it cannot start a
process. It can only talk to something already listening on localhost. The bridge
(`chat-bridge.py`) is exactly that — but somebody has to start the bridge, and until
now that somebody was the reader, typing `pe-chat <dir>` in a terminal.

This is a very small, very dull daemon that closes that last gap. It listens on
127.0.0.1:8790 and does one useful thing: given the *name* of an exploration in the
library, it starts a bridge for it and reports the port. The page's refresh control
calls it when no bridge answers, so a reader who opens a page with nothing running
gets a working chat by clicking the refresh icon — no terminal, no command to copy.

    ./pe-launchd.py [--port 8790] [--once]

Endpoints
    GET  /health  -> {"ok":true,"launcher":true,"library":"…","claude":true,
                      "version":"…","explorations":[…],"bridges":{"<slug>":port}}
    POST /start   -> {"ok":true,"port":8787,"already":false,"claude":true,"slug":"…"}
                     {"error":"unknown-exploration"}  404 — not a folder in the library
                     {"error":"no-free-port"}         503 — 8787-8789 all taken
                     {"error":"no-claude"}            503 — nothing named claude on PATH
                     Body: {"exploration":"<slug>"} — a folder name, never a path.

What it will NOT do, on purpose:
  * It takes a **slug**, not a path. The slug is resolved against the library root and
    must be a direct child of it holding an index.html. A page cannot talk this daemon
    into running a bridge over some other part of the filesystem, and cannot smuggle a
    path through: `..`, `/` and `~` are rejected before anything is resolved.
  * It runs one fixed command — chat-bridge.py, from the plugin it was installed with —
    with a fixed argument shape. Nothing from the request reaches a shell.
  * It binds 127.0.0.1. Nothing off this machine can reach it.

Lifetime: the opposite of the bridge's. A bridge belongs to one open page and dies with
it; this daemon belongs to the login session and just sits there, costing nothing, so
that the *next* page has something to ask. It is installed as a LaunchAgent by
`setup.sh` and removed by `setup.sh --uninstall-launcher`.
"""
import argparse, json, os, re, shutil, socket, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

BRIDGE_PORTS = (8787, 8788, 8789)     # the same three the page probes
START_TIMEOUT = 25                    # a cold `claude --version` is the slow part
MAX_BODY = 8 * 1024
SLUG_OK = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")

HERE = os.path.dirname(os.path.realpath(__file__))
BRIDGE = os.path.join(HERE, "chat-bridge.py")

_start_lock = threading.Lock()        # two pages clicking refresh at once must not race
_spawned = []                        # bridges we started, so their exits can be reaped
_spawned_lock = threading.Lock()


def reap_spawned():
    """Clear out the bridges that have exited.

    This daemon starts bridges and deliberately does not supervise them — but it is
    still their parent, and a parent that never waits leaves a zombie behind for every
    bridge that has ever closed with its page. They cost nothing to run and everything
    to trust: a `.chat-bridge.port` naming a zombie pid answers a liveness check with
    "still here" for the rest of the login session. Nothing here waits or blocks; a
    bridge still serving a page is simply skipped."""
    with _spawned_lock:
        alive = [p for p in _spawned if p.poll() is None]
        _spawned[:] = alive


def library_root():
    return os.path.join(os.environ.get("PE_HOME") or
                        os.path.join(os.path.expanduser("~"), ".process-enablement"), "output")


def explorations():
    root = library_root()
    if not os.path.isdir(root):
        return []
    return sorted(n for n in os.listdir(root)
                  if SLUG_OK.match(n)
                  and os.path.isfile(os.path.join(root, n, "index.html")))


def resolve(slug):
    """A library folder name -> its absolute path, or None. Paths are not accepted.

    The whole security model of this daemon is this function: the only directories it
    will ever hand to a bridge are direct children of the library that already hold a
    rendered page. Anything else — a path, a traversal, a symlink pointing out of the
    library — returns None and the caller answers 404."""
    slug = (slug or "").strip()
    if not slug or not SLUG_OK.match(slug) or os.sep in slug or slug in (".", ".."):
        return None
    root = os.path.realpath(library_root())
    d = os.path.realpath(os.path.join(root, slug))
    if os.path.dirname(d) != root or not os.path.isfile(os.path.join(d, "index.html")):
        return None
    return d


def probe(port, timeout=0.9):
    try:
        with urlopen("http://127.0.0.1:%d/health" % port, timeout=timeout) as r:
            h = json.load(r)
        return h if h.get("ok") else None
    except Exception:
        return None


def bridges():
    """Which bridges are up right now, by the exploration each one sits in."""
    reap_spawned()
    out = {}
    for port in BRIDGE_PORTS:
        h = probe(port)
        if h:
            out[os.path.basename(str(h.get("dir", "")).rstrip("/"))] = port
    return out


def serving(slug):
    """A bridge that can act for this exploration: its own, or a sibling's in the
    same library — the bridge already serves its whole library, so a second one for
    the folder next door would be waste."""
    for port in BRIDGE_PORTS:
        h = probe(port)
        if not h or not h.get("claude"):
            continue
        if os.path.basename(str(h.get("dir", "")).rstrip("/")) == slug:
            return port, h
        if slug in (h.get("siblings") or {}):
            return port, h
    return None, None


def free_port():
    for port in BRIDGE_PORTS:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return None


def login_path():
    """A LaunchAgent inherits a bare PATH, and `claude` is usually in ~/.local/bin,
    a version manager's shim dir, or Homebrew — none of which are on it. Ask the
    user's own login shell once, and fall back to something sensible."""
    guesses = [os.path.expanduser("~/.local/bin"), os.path.expanduser("~/.claude/local"),
               "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin",
               "/usr/sbin", "/sbin"]
    shell = os.environ.get("SHELL") or "/bin/zsh"
    try:
        out = subprocess.run([shell, "-l", "-c", "printf %s \"$PATH\""],
                             capture_output=True, text=True, timeout=15).stdout.strip()
        if out:
            return out + ":" + ":".join(guesses)
    except Exception:
        pass
    return ":".join(guesses)


_PATH = None


def env_for_bridge():
    global _PATH
    if _PATH is None:
        _PATH = login_path()
    env = dict(os.environ)
    env["PATH"] = _PATH
    return env


def spawn(workdir, port):
    """Start a bridge, detached, and wait until it actually answers.

    Detached matters: this daemon must not become the bridge's supervisor. The bridge
    manages its own life — it goes away when the page that asked for it closes — and if
    this daemon is ever restarted it must not drag a live bridge down with it."""
    log = os.path.join(workdir, ".chat-bridge.log")
    try:
        out = open(log, "a")
    except Exception:
        out = subprocess.DEVNULL
    reap_spawned()
    proc = subprocess.Popen([sys.executable, BRIDGE, "--dir", workdir, "--port", str(port)],
                            stdout=out, stderr=out, stdin=subprocess.DEVNULL,
                            cwd=workdir, env=env_for_bridge(), start_new_session=True)
    with _spawned_lock:
        _spawned.append(proc)
    deadline = time.time() + START_TIMEOUT
    while time.time() < deadline:
        h = probe(port, timeout=1.2)
        if h:
            return h
        time.sleep(0.4)
    return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "pe-launchd/1"

    def log_message(self, fmt, *a):
        sys.stderr.write("  %s\n" % (fmt % a))

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8", "replace")) or {}
        except Exception:
            return {}

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        if self.path.rstrip("/").split("?")[0] not in ("", "/health"):
            return self._send(404, {"error": "no-such-route"})
        exe = shutil.which("claude", path=env_for_bridge()["PATH"])
        ver = ""
        if exe:
            try:
                ver = subprocess.run([exe, "--version"], capture_output=True, text=True,
                                     timeout=20).stdout.strip()
            except Exception:
                ver = ""
        self._send(200, {"ok": True, "launcher": True, "version": ver,
                         "claude": bool(exe), "library": library_root(),
                         "explorations": explorations(), "bridges": bridges()})

    def do_POST(self):
        if self.path.rstrip("/") != "/start":
            return self._send(404, {"error": "no-such-route"})
        slug = (self._body().get("exploration") or "").strip()
        workdir = resolve(slug)
        if not workdir:
            return self._send(404, {"error": "unknown-exploration", "slug": slug,
                                    "library": library_root()})
        with _start_lock:                       # one start at a time, whoever asked first
            port, h = serving(slug)
            if port:
                return self._send(200, {"ok": True, "port": port, "already": True,
                                        "claude": True, "slug": slug,
                                        "version": h.get("version", "")})
            if not shutil.which("claude", path=env_for_bridge()["PATH"]):
                return self._send(503, {"error": "no-claude", "slug": slug})
            port = free_port()
            if not port:
                return self._send(503, {"error": "no-free-port", "slug": slug,
                                        "bridges": bridges()})
            h = spawn(workdir, port)
        if not h:
            return self._send(504, {"error": "start-timed-out", "slug": slug, "port": port})
        self._send(200, {"ok": True, "port": port, "already": False, "slug": slug,
                         "claude": bool(h.get("claude")), "version": h.get("version", "")})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--once", action="store_true",
                    help="report what it would serve, then exit — for setup.sh")
    a = ap.parse_args()
    if a.once:
        print("library:      %s" % library_root())
        print("explorations: %s" % (", ".join(explorations()) or "none"))
        print("bridge:       %s" % (BRIDGE if os.path.isfile(BRIDGE) else "MISSING " + BRIDGE))
        print("claude:       %s" % (shutil.which("claude", path=env_for_bridge()["PATH"]) or "NO"))
        return 0 if os.path.isfile(BRIDGE) else 1
    # Reap on a timer as well as on demand. /health reaps whenever a page asks, but a
    # reader who closes the last tab and walks away asks nothing more, and the exited
    # bridge would sit as a zombie until the next visit.
    def reaper():
        while True:
            time.sleep(30)
            reap_spawned()
    threading.Thread(target=reaper, daemon=True).start()

    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print("Process Exploration launcher → http://127.0.0.1:%d" % a.port)
    print("  library %s" % library_root())
    print("  POST /start {\"exploration\":\"<folder>\"} starts a bridge for it")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
