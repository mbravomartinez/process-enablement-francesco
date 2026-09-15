#!/usr/bin/env python3
"""
Local bridge between a generated Process Exploration page and the Claude Code CLI
on this machine.

The page is a file:// document, so it cannot start a process. It can, however, POST
to localhost. This server accepts a question plus the reader's on-page context, asks
the local `claude` CLI to answer it as the industry-expert agent, and returns the
answer as JSON. Nothing leaves the machine except whatever the CLI itself sends.

    ./chat-bridge.py --dir <exploration-dir> [--port 8787]

Endpoints
    GET  /health    -> {"ok":true,"claude":true,"version":"…","dir":"…","languages":[…]}
    POST /ask       -> {"topic":…,"what":…,"why":…,"example":…}
                       or {"error":"no-claude"} with 503 when the CLI is absent.
    POST /translate        -> {"file":"index.it.html","cached":false}
    POST /translate/cancel -> {"cancelled":true} — stops a render started by mistake
                       Renders a language that does not exist yet by asking the CLI to
                       translate this exploration's page, then validating the result.
    POST /translate/notes  -> {"notes":{"<id>":{…}}} — the reader's own notes, in one language
    POST /beat      -> {"ok":true,"beat":15} — the open page, still open
    POST /bye       -> {"ok":true,"stopping":true} — the tab is closing

Binds 127.0.0.1 only.

Lifetime: the bridge belongs to the page. It shuts down when the last open page goes
away — on /bye from a closing tab, or on a heartbeat that stops arriving — and takes
every `claude` subprocess it started with it. A page from an older generation never
beats: it is served by the idle reaper instead, which retires the bridge after
IDLE_EXIT. The exploration on disk is never touched; only a translation caught
mid-render is discarded. `--keep-alive` opts out.
"""
import argparse, concurrent.futures as cf, glob, json, os, re, shutil, signal, \
       subprocess, sys, threading, time
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ASK_TIMEOUT = 180
IDLE_EXIT = 12 * 3600             # no request for this long -> the bridge retires itself
REAP_EVERY = 60                   # how often the reaper looks at its own directory
TRANSLATE_TIMEOUT = 1800          # a full page is a long job; the browser shows a timer
MAX_BODY = 32 * 1024
NOTES_BODY = 1024 * 1024        # a reader's whole notebook, not a single question

LANGS = {"en": "English", "it": "Italian", "de": "German", "fr": "French",
         "es": "Spanish", "ar": "Arabic", "pt": "Portuguese", "nl": "Dutch"}

_translating = {}                 # (workdir, code) -> {"cancel": bool, "procs": [Popen]}


# ---------------------------------------------------------------------------
# Session lifecycle: the page owns the bridge's life
#
# The bridge exists to serve one open page. When the reader closes the tab, the
# page says goodbye (navigator.sendBeacon) and the bridge tears itself down —
# every `claude` subprocess it started included. A closed tab that never got to
# say goodbye (a crash, a killed browser) is caught by the heartbeat instead: the
# page beats every BEAT_EVERY seconds and a client that has gone quiet for
# CLIENT_TTL is treated as gone.
#
# What is never touched on the way out: the exploration's own files — content.md,
# research/, context/, any finished index.<lang>.html, and the registry. Those are
# the enablement, and they outlive the session. Only a translation that was still
# mid-render is cleaned up, because a half-written page is not worth keeping.
# ---------------------------------------------------------------------------
BEAT_EVERY = 15                   # the page's heartbeat interval, seconds
# A hidden tab is not a closed tab, but a browser treats its timers as if it were: Chrome
# throttles an interval in a backgrounded page to roughly one call a minute. At the old 50s
# the arithmetic decided the question: a reader who asked something and switched tabs while
# waiting fell out of the window between two throttled beats, and the bridge retired itself
# mid-answer — taking the `claude` running the answer with it. 150s clears a once-a-minute
# beat twice over. The cost is that a genuinely dead browser is noticed later, which nothing
# depends on: the port is freed either way, and the idle reaper is the real backstop.
CLIENT_TTL = 150                  # no beat for this long and the page is gone
BYE_GRACE = 8                     # a "bye" may be a reload — wait before acting
WATCH_TICK = 2

_clients = {}                     # session id -> last beat, monotonic seconds
_clients_lock = threading.Lock()
_saw_client = False               # never auto-exit before a page has ever connected
_procs = set()                    # every live `claude` child, so none is orphaned
_procs_lock = threading.Lock()
_shutting_down = threading.Event()
_autoexit = True
# /ask calls in flight. A translation already keeps the bridge alive past its page, for the
# same reason an answer must: the reader asked for it, the CLI is running, and exiting now
# throws the work away and reports it to the page as a lost connection.
_asking = [0]
_asking_lock = threading.Lock()


def spawn(cmd, **kw):
    """Start a child in its own process group, and remember it.

    The group matters: `claude` starts children of its own, and terminating only the
    process we can see leaves those behind as orphans. Its own group means one signal
    reaches the whole tree."""
    kw.setdefault("start_new_session", True)
    proc = subprocess.Popen(cmd, **kw)
    with _procs_lock:
        _procs.add(proc)
    return proc


def stop_tree(proc, sig=signal.SIGTERM):
    """Signal a child and everything it started."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.terminate() if sig == signal.SIGTERM else proc.kill()
        except Exception:
            pass


def reap(proc):
    with _procs_lock:
        _procs.discard(proc)


def kill_children():
    """Terminate every `claude` we started, then insist."""
    with _procs_lock:
        procs = list(_procs)
        _procs.clear()
    for proc in procs:
        stop_tree(proc, signal.SIGTERM)
    deadline = time.time() + 5
    for proc in procs:
        try:
            proc.wait(timeout=max(0.1, deadline - time.time()))
        except Exception:
            stop_tree(proc, signal.SIGKILL)
    return len(procs)


def clear_portfile(workdir):
    """Remove the "a bridge lives here" marker on the way out.

    It is written at startup so the library can find a live bridge without probing. A
    bridge that exits without removing it leaves a file naming a dead pid, and the next
    reader of the library is told a bridge is up when nothing is listening."""
    try:
        os.remove(os.path.join(workdir, ".chat-bridge.port"))
    except (FileNotFoundError, OSError):
        pass


def cancel_translations(workdir):
    """Stop the running translations but KEEP what they earned.

    This used to delete every `.partial`, on the reasoning that an interrupted render should
    leave nothing behind. It leaves the reader worse off: `translate()` uses a partial as its
    base and re-sends only the strings still English, so a run stopped at 32% resumes at 32%
    when the partial survives and starts from nothing when it does not — and a reload that
    retires the bridge is exactly how a run gets stopped."""
    kept = []
    for state in list(_translating.values()):
        state["cancel"] = True
    for path in glob.glob(os.path.join(workdir, "index.*.html.partial")):
        kept.append(os.path.basename(path))
    return kept


def shutdown(srv, why):
    """Stop serving, kill the children, keep the exploration."""
    if _shutting_down.is_set():
        return
    _shutting_down.set()
    n = kill_children()
    partials = cancel_translations(srv.workdir)
    clear_portfile(srv.workdir)
    print("\nbridge stopping — %s" % why, file=sys.stderr)
    if n:
        print("  stopped %d claude subprocess%s" % (n, "" if n == 1 else "es"), file=sys.stderr)
    if partials:
        print("  kept unfinished %s — pick 'finish' in the language menu to carry on"
              % ", ".join(partials), file=sys.stderr)
    print("  kept the exploration in %s" % srv.workdir, file=sys.stderr)
    threading.Thread(target=srv.shutdown, daemon=True).start()


def note_beat(sid):
    global _saw_client
    if not sid:
        return
    with _clients_lock:
        _clients[sid] = time.monotonic()
        _saw_client = True


def note_bye(sid):
    """A tab closed. Do not act yet — a reload looks exactly like this."""
    with _clients_lock:
        _clients.pop(sid, None)
        _clients[sid + "\x00bye"] = time.monotonic() - (CLIENT_TTL - BYE_GRACE)
        # the placeholder expires in BYE_GRACE seconds; a reload beats before then


def watchdog(srv):
    """Exit once every page that was open has gone — unless work is still running.

    A reload is indistinguishable from a close for a moment, and that moment used to be enough
    to retire the bridge in the middle of a translation the reader had just started. Work the
    reader asked for outlives the page that asked for it: while anything is in `_translating`
    the bridge stays up, finishes it, and writes the language beside the page. The reloaded page
    finds it again through /jobs."""
    waiting = False
    while not _shutting_down.is_set():
        time.sleep(WATCH_TICK)
        now = time.monotonic()
        with _clients_lock:
            for sid, last in list(_clients.items()):
                if now - last > CLIENT_TTL:
                    _clients.pop(sid, None)
            live, saw = len(_clients), _saw_client
        if saw and not live:
            busy = [code for (_wd, code) in list(_translating.keys())]
            with _asking_lock:
                answering = _asking[0]
            if busy or answering:
                if not waiting:
                    waiting = True
                    what = []
                    if answering:
                        what.append("%d question%s" % (answering, "" if answering == 1 else "s"))
                    if busy:
                        what.append("translating " + ", ".join(sorted(busy)))
                    print("  page gone, but still answering %s — staying up until it lands"
                          % " and ".join(what), file=sys.stderr)
                continue
            return shutdown(srv, "the page was closed")
        waiting = False


class Cancelled(Exception):
    """Raised when the reader stops a translation from the page."""

BATCH_PROMPT = """Translate each numbered line below into {language}.

These are user-visible strings from a process-enablement page about {topic}.

Rules:
- Translate the meaning, keep the register: plain, professional, present tense.
- **Keep untranslated**: company, product and place names; airport and airline codes; and
  terms of art — IROPS, FDP, FDTL, OTP, OTP15, OTIF, DSO, MCT, ETOPS, GCAA, EU261, PNR, DCS,
  OCC, IOC, AOCC, BRS, SSIM, ASM, SSM, MVT, PNL, ADL, ACARS, ATC, MRO, DXB, DWC, KTM, BAH,
  tail swap, off-block, on-block, no-show, standby.
- Preserve any inline HTML tags exactly as they appear (`<b>`, `<i>`, `<br>`, `<p>`, `<span …>`)
  and keep every `${{…}}` placeholder untouched and in place.
- Preserve leading and trailing spaces, and never add or remove a line.
- A line may contain the two characters `\n`. That is a line break inside a structured note
  example: keep every one of them, the same number in the same places, and translate the short
  label in front of each.

Return **only** a JSON object mapping each number to its translation, nothing else:
{{"1":"…","2":"…"}}

Lines:
{lines}
"""


# Strings that must never be treated as prose: identifiers, codes, css-ish tokens.
SKIP_RE = re.compile(r"""^(?:[a-z0-9_\-]+|[A-Z_]+|#[0-9a-fA-F]{3,8}|\d[\d.,%/ ]*|
                          [a-z]+:[a-z0-9 .\-]+|index(?:\.[a-z]{2})?\.html|
                          [a-z]+(?:-[a-z]+)+)$""", re.X)
KEEP_ALWAYS = {"Overview", "KPIs", "Terminology", "Personal Notes", "Quiz", "Export",
               "Process Step-by-Step", "Process Challenges", "Steps", "Common deviations",
               "Language", "Process", "Industry", "Who does it", "What happens",
               "This order, at this step", "Documents that now exist"}


# A statement, not a sentence. Kept narrow on purpose: a bare keyword match rejected
# real prose ("for their operations control, crew management, ..."), so each keyword
# has to be followed by the punctuation that makes it code.
CODE_START_RE = re.compile(r"""^(?: (?:let|const|var)\s+[A-Za-z_$][\w$]*\s*[=;]
                                  | (?:if|for|while|switch|catch)\s*\(
                                  | (?:function|class)\s+[A-Za-z_$]
                                  | return\s+[\w$'"(\[]
                                  )""", re.X)


def class_values(html):
    """Every value a class attribute takes in this page.

    A class list reads like prose to a string extractor ("btn ghost push") and like an
    instruction to a translator, which then renames the class and unstyles the button.
    Collected by value so such a string can be refused wherever it turns up."""
    out = set()
    for m in re.finditer(r"""class(?:Name)?\s*=\s*["']([^"'{}<>]{2,})["']""", html):
        out.add(m.group(1).strip())
    return out


def walk_js(js, add):
    """Feed every prose string in one JS span to `add`.

    Comments must go first: an apostrophe in a comment ("the reader's own record") would
    otherwise open a false single-quoted span and swallow every string until the next
    apostrophe — which is how whole KPI and problem paragraphs once went missing."""
    js = re.sub(r"/\*[\s\S]*?\*/", " ", js)
    js = re.sub(r"(?m)^\s*//.*$", " ", js)
    i, n = 0, len(js)
    while i < n:
        c = js[i]
        if c == '"':
            j, buf = i + 1, []
            while j < n:
                if js[j] == "\\":
                    buf.append(js[j:j + 2]); j += 2; continue
                if js[j] == '"':
                    break
                buf.append(js[j]); j += 1
            add("".join(buf))
            i = j + 1
        elif c in "'`":
            j = i + 1
            while j < n:
                if js[j] == "\\":
                    j += 2; continue
                if js[j] == c:
                    break
                j += 1
            if c == "`":
                # Template literals carry the interface labels ("Concept — what the
                # mechanism is", "Most probable root causes"). Strip the ${…} holes and
                # the tags, then take the text that is left.
                span = re.sub(r"\$\{[^{}]*\}", "\x00", js[i + 1:j])
                for chunk in span.split("\x00"):
                    for piece in re.findall(r">([^<>]{2,})<", chunk):
                        add(re.sub(r"\s+", " ", piece))
                    plain = re.sub(r"<[^>]*>", " ", chunk)
                    for piece in re.split(r"\s{2,}|\n", plain):
                        piece = piece.strip().strip(":").strip()
                        if len(piece) > 3 and " " in piece:
                            add(piece)
            i = j + 1
        else:
            i += 1



def extract_strings(html):
    """Every user-visible string in the page, in document order, de-duplicated.

    Two sources, both conservative: quoted literals inside the JS data blocks (which hold
    the prose), and text nodes plus a few attributes in the markup. Anything that looks
    like an identifier, code, colour or number is skipped."""
    found, seen = [], set()
    classes = class_values(html)

    def add(s):
        s2 = s.strip()
        if len(s2) < 2 or len(s2) > 1200 or s2 in seen:
            return
        if "\n" in s2 or "<svg" in s2 or "viewBox" in s2 or "=>" in s2:
            return                                     # markup or code, not prose
        if "${" in s2 or "`" in s2:
            return                                     # template expression, not prose
        if CODE_START_RE.match(s2) or re.search(r";\s*(?:[a-z_$][\w$]*\s*=|if\s*\()", s2):
            return                                     # a statement, not a sentence
        if s2 in classes:
            return                                     # a class list — translating it unstyles the page
        bare = re.sub(r"<[^>]*>", "", s2).strip()
        if len(re.findall(r"[A-Za-z]", bare)) < 3:
            return                                     # pure markup, no words of its own
        if re.match(r"^[,;{}\[\]]", s2) or re.search(r"\b[a-z]+:$", s2):
            return                                     # spillover between object keys
        if not (s2[0].isalnum() or s2[0] in "<\u201c\u2018\"'\u20ac$"):
            return                                     # starts with a symbol \u2192 code
        if '="' in s2 or s2.endswith("=") or re.search(r"[)(]\+|\+[a-z]+\(", s2):
            return                                     # attribute or expression fragment
        if re.fullmatch(r"[A-Z0-9\u2192/\- ]+", s2):      # DXB\u2192KTM, A6-FZZ, OTP15
            return
        if re.fullmatch(r"\d{1,2} [A-Z][a-z]{2} \d{4}|\d{1,2}:\d{2}", s2):
            return                                     # dates and clock times
        if s2 not in KEEP_ALWAYS:
            if SKIP_RE.match(s2) or not re.search(r"[A-Za-z]{3}", s2):
                return
            if " " not in s2 and s2[0].islower():      # lone lowercase token → identifier
                return
        seen.add(s2); found.append(s2)

    # 1. JS spans — walked, not regexed.
    #    A quote-pair regex drifts out of alignment the moment one escaped quote appears
    #    earlier in the region, and silently stops capturing prose after it. Walk the text
    #    instead: pair double quotes properly, and skip single-quoted and template spans
    #    wholesale (apostrophes and ${...} live there).
    #
    #    Two spans, and the second is deliberate belt-and-braces. The data block span runs to
    #    `const REGISTRY=`, which today sits after the chrome, so the tour copy already falls
    #    inside it — by position, not by intent. Naming the tour span explicitly is what stops
    #    a future reordering from silently dropping twelve steps of prose from every language.
    #    Overlap costs nothing: `add()` de-duplicates.
    for start, end in (("const EX=", "const REGISTRY="),
                       ("/* PE:tour-copy", "/* PE:tour-copy-end */")):
        try:
            a = html.index(start); b = html.index(end, a)
        except ValueError:
            continue
        walk_js(html[a:b], add)

    # 2. markup: text nodes and the attributes a reader sees
    body = html[html.index("<body"):html.rindex("<script>")] if "<body" in html else ""
    body = re.sub(r"<svg[\s\S]*?</svg>", "", body)             # geometry, not prose
    for m in re.finditer(r">([^<>{}]{2,})<", body):
        add(re.sub(r"\s+", " ", m.group(1)))
    for attr in ("title", "aria-label", "placeholder", "alt"):
        for m in re.finditer(attr + r'="([^"{}]{2,})"', body):
            add(m.group(1))
    return found


LANGS_LABEL = {"en": "English", "it": "Italiano", "de": "Deutsch", "fr": "Français",
               "es": "Espa\u00f1ol", "ar": "\u0627\u0644\u0639\u0631\u0628\u064a\u0629",
               "pt": "Portugu\u00eas", "nl": "Nederlands"}


def stamp_languages(page, by_slug):
    """Rewrite every entry's `languages:[…]` in a page's stamped REGISTRY snapshot.

    An entry is found by its own `path:'<slug>'` and only the array that follows it is
    touched, so a translated page keeps its localised process and industry labels.
    Appending to the first `languages:[` in the file, as this used to do, wrote the new
    language onto whichever exploration sorted first: a sibling was credited with a file
    it does not have, and switching process there hit ERR_FILE_NOT_FOUND."""
    out, i, changed = [], 0, False
    for m in re.finditer(r"path:'([A-Za-z0-9][A-Za-z0-9._-]*)'", page):
        langs = by_slug.get(m.group(1))
        if not langs:
            continue
        a = page.find("languages:[", m.end())
        b = page.find("]", a) if a >= 0 else -1
        if a < 0 or b < 0:
            continue
        want = "languages:[" + ",".join(
            "{code:'%s',label:'%s',file:'%s'}"
            % (l["code"], str(l["label"]).replace("'", "\\'"), l["file"]) for l in langs)
        if page[a:b] == want:
            continue
        out.append(page[i:a])
        out.append(want)
        i, changed = b, True
    return ("".join(out) + page[i:]) if changed else None


def restamp_registry(workdir):
    """Bring every page in the LIBRARY up to date with registry.json.

    A page reads its stamped REGISTRY snapshot when no bridge is running, so a language
    that exists on disk but is missing from the snapshot looks ungenerated. That snapshot
    is also what a process/industry switch navigates by — it carries the sibling's
    languages, not just this page's — so restamping only the directory that gained the
    language left every other exploration pointing at the wrong file. Every page in every
    exploration is restamped, and a language whose file is not actually on disk is dropped
    rather than stamped, so a stale registry entry cannot send a reader to a missing page."""
    root = library_root(workdir)
    try:
        data = json.load(open(os.path.join(root, "registry.json"), encoding="utf-8"))
    except Exception:
        return []
    by_slug = {}
    for e in data.get("explorations", []):
        slug = e.get("path")
        if not slug or not SLUG_OK.match(slug):
            continue
        by_slug[slug] = [l for l in (e.get("languages") or [])
                         if l.get("file") and os.path.isfile(os.path.join(root, slug, l["file"]))]
    touched = []
    for slug in sorted(by_slug):
        d = os.path.join(root, slug)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not re.fullmatch(r"index(\.[a-z]{2})?\.html", name):
                continue
            try:
                fp = os.path.join(d, name)
                new = stamp_languages(open(fp, encoding="utf-8").read(), by_slug)
                if new:
                    open(fp, "w", encoding="utf-8").write(new)
                    touched.append(os.path.join(slug, name))
            except Exception:
                pass
    return touched


def register_language(workdir, code, label, filename):
    """Record the new language everywhere it has to be known.

    registry.json is the source of truth; the pages carry a snapshot of it because a
    file:// page cannot fetch local JSON. Write the truth first, then restamp."""
    reg = os.path.join(library_root(workdir), "registry.json")
    touched = []
    try:
        data = json.load(open(reg, encoding="utf-8"))
        me = os.path.basename(os.path.realpath(workdir))
        for e in data.get("explorations", []):
            if e.get("path") == me:
                if not any(l.get("code") == code for l in e.setdefault("languages", [])):
                    e["languages"].append({"code": code, "label": label,
                                           "file": filename,
                                           "generated": time.strftime("%Y-%m-%d")})
                    e["updated"] = time.strftime("%Y-%m-%d")
        json.dump(data, open(reg, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        touched.append("registry.json")
    except Exception:
        pass
    return touched + restamp_registry(workdir)


# A note's `example` is written as several short labelled lines, so a field handed to the
# translator can contain real newlines — which would break a numbered list outright, the
# tail of one value reading as an unnumbered line of its own. Send the breaks escaped and
# restore them on the way back; the prompt tells the translator to keep them in place.
def _enc_nl(s):
    return s.replace("\\", "\\\\").replace("\n", "\\n")


def _dec_nl(s):
    return re.sub(r"\\(n|\\)", lambda m: "\n" if m.group(1) == "n" else "\\", s)


def translate_batch(exe, workdir, language, topic, lines, offset, state=None, code=""):
    numbered = "\n".join("%d. %s" % (offset + k, _enc_nl(s)) for k, s in enumerate(lines))
    prompt = BATCH_PROMPT.format(language=language, topic=topic, lines=numbered)
    proc = spawn([exe, "-p", prompt, "--output-format", "json"],
                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                 text=True, cwd=workdir)
    if state is not None:
        state.setdefault("procs", []).append(proc)
    deadline = time.time() + 300
    while True:
        try:
            out, err = proc.communicate(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            if _shutting_down.is_set() or (state is not None and state.get("cancel")):
                stop_tree(proc, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except Exception:
                    stop_tree(proc, signal.SIGKILL)
                raise Cancelled()
            if time.time() > deadline:
                stop_tree(proc, signal.SIGKILL)
                raise RuntimeError("batch timed out")
    reap(proc)
    if state is not None:
        try:
            state.get("procs", []).remove(proc)
        except ValueError:
            pass
    if proc.returncode != 0:
        raise RuntimeError((err or out or "")[-300:])
    raw = (out or "").strip()
    try:
        raw = json.loads(raw).get("result", raw)
    except Exception:
        pass
    obj = extract_json(raw if isinstance(raw, str) else json.dumps(raw))
    if not isinstance(obj, dict):
        # Guessing at an answer we threw away cost a whole afternoon once: write it down.
        where = ""
        try:
            name = ".chat-bridge-batch-%s-%d+%d.txt" % (code or "xx", offset, len(lines))
            with open(os.path.join(workdir, name), "w", encoding="utf-8") as fh:
                fh.write((out or "")[:65536])
            where = " (kept in %s)" % name
        except Exception:
            pass
        raise RuntimeError("batch did not return a JSON object%s" % where)
    return {int(k): (_dec_nl(v) if isinstance(v, str) else v)
            for k, v in obj.items() if str(k).isdigit()}


def translate_chunk(exe, workdir, code, topic, lines, offset, state=None, depth=0):
    """One batch, but a bad answer is retried in halves rather than sinking the pass.

    Asking for eighty strings back as one JSON object is a lot to ask, and the failure
    mode is an answer that will not parse — truncated, or wrapped in prose. Halving the
    question is the cheapest fix that has ever worked here, so a chunk that fails is
    split and each half asked once more. Only a single string that still fails raises."""
    try:
        return translate_batch(exe, workdir, LANGS[code], topic, lines, offset, state, code)
    except Cancelled:
        raise
    except Exception as e:
        if len(lines) < 2 or depth >= 2:
            raise
        half = len(lines) // 2
        log_run(code, "batch %d-%d failed — retrying in halves"
                % (offset, offset + len(lines) - 1), detail=str(e)[:120])
        got = {}
        for start, part in ((offset, lines[:half]), (offset + half, lines[half:])):
            got.update(translate_chunk(exe, workdir, code, topic, part, start, state, depth + 1))
        return got


def log_run(code, msg, **facts):
    """Say what a translation did, in the log.

    A run reports to the page that asked for it — and that page may be gone: a reload drops the
    connection the answer would have travelled down. Then an error nobody received explained why
    a language "just went back to translate". So every outcome is written here as well, where it
    survives the reader."""
    tail = " ".join("%s=%s" % (k, v) for k, v in facts.items() if v not in (None, ""))
    print("  [%s %s] %s%s" % (time.strftime("%H:%M:%S"), code, msg, (" " + tail) if tail else ""),
          file=sys.stderr, flush=True)


def job_elapsed(state):
    """Seconds this translation has been running — so a reloaded page's clock is honest."""
    now = time.time()
    return max(0.0, now - (state.get("t0") or now))


COMPLETE = 0.995     # coverage at which a page counts as fully translated
MAX_PASSES = 3       # top-up passes inside one request, so one click can finish a page
EXTRA_PASSES = 2     # more passes, earned only when a batch broke — retrying is the whole point


def substitute(doc, source, target):
    """Replace every occurrence of one string, escaped for the delimiter it sits inside.

    Longest strings are substituted first by the caller, so a short string never
    corrupts a longer one containing it. An Italian apostrophe dropped into a
    single-quoted JS literal would break the page, hence the per-occurrence escape."""
    hits, pos, pieces = 0, 0, []
    while True:
        k = doc.find(source, pos)
        if k < 0:
            break
        before = doc[k - 1] if k else ""
        after = doc[k + len(source)] if k + len(source) < len(doc) else ""
        repl = target
        if before == "'" or after == "'":
            repl = repl.replace("\\", "\\\\").replace("'", "\\'")
        elif before == '"' or after == '"':
            repl = repl.replace("\\", "\\\\").replace('"', '\\"')
        pieces.append(doc[pos:k]); pieces.append(repl)
        pos = k + len(source); hits += 1
    pieces.append(doc[pos:])
    return "".join(pieces), hits


def fit_to_source(src, val):
    """A translation only as the page can hold it — or nothing.

    Every extracted string is a single line inside a quoted JS literal, so a translation
    that arrives with a real line break cannot be substituted: it terminates the literal
    and the page stops parsing ("SyntaxError: Invalid or unexpected token"). It arrives
    that way often, because a note example carries the two characters `\n` and the model
    answers with one real newline instead — `_dec_nl()` cannot tell the two apart.

    So a newline is written back in the convention the source used, and the handful of
    characters that would break out of the literal whatever we do are refused."""
    if not isinstance(val, str):
        return None
    if "\r" in val or "\n" in val:
        if "\\n" in src:                    # the source carries literal backslash-n escapes
            val = re.sub(r"\r\n?|\n", lambda m: "\\n", val)
        else:
            val = re.sub(r"[\r\n\t]+", " ", val)
    val = val.strip()
    if not val:
        return None
    # A backtick or a `${` dropped into a template literal, or a closing script tag
    # anywhere, breaks the page no matter how it is escaped. Leave the English.
    if "`" in val or "${" in val and "${" not in src or "</script" in val.lower():
        return None
    return val


def js_span(page):
    """The page's own script, as text — the thing `node --check` has an opinion about."""
    return page[page.rindex("<script>") + 8:page.rindex("</script>")]


def js_parses(page, node=None):
    """Does this page's script still parse? Used both to check and to repair."""
    node = node or shutil.which("node")
    if not node:
        return True                          # no judge available; do not invent a verdict
    import tempfile
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(js_span(page)); path = fh.name
    except Exception:
        return True
    try:
        return subprocess.run([node, "--check", path],
                              capture_output=True, text=True, timeout=60).returncode == 0
    except Exception:
        return True
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def mend_js(js):
    """Close every string literal a stray newline left open. Returns (js, mends).

    A translated `\n` that came back as a real newline terminates the literal it lands in,
    and once such a page has been written to disk every run that resumes from it inherits
    the breakage — which is how a page sat at 52% no matter how well the next pass went.
    Walk the script honouring quotes, comments and template literals, and write the newline
    back as the escape it was meant to be."""
    out, i, n, quote, mends = [], 0, len(js), None, 0
    while i < n:
        c = js[i]
        if quote:
            if c == "\\" and i + 1 < n:
                out.append(js[i:i + 2]); i += 2; continue
            if c == quote:
                quote = None; out.append(c); i += 1; continue
            if c == "\n" and quote in "\"'":
                out.append("\\n"); mends += 1; i += 1; continue
            out.append(c); i += 1; continue
        if c in "\"'`":
            quote = c; out.append(c); i += 1; continue
        if js[i:i + 2] == "//":
            j = js.find("\n", i); j = n if j < 0 else j
            out.append(js[i:j]); i = j; continue
        if js[i:i + 2] == "/*":
            j = js.find("*/", i); j = n if j < 0 else j + 2
            out.append(js[i:j]); i = j; continue
        out.append(c); i += 1
    return "".join(out), mends


def mend_page(page):
    """A page whose script parses again, or None. Never returns a page that is still broken."""
    if js_parses(page):
        return page
    try:
        js = js_span(page)
    except ValueError:
        return None
    fixed, mends = mend_js(js)
    if not mends:
        return None
    cand = page[:page.rindex("<script>") + 8] + fixed + page[page.rindex("</script>"):]
    return cand if js_parses(cand) else None


def write_page(path, page, code, what):
    """Write a page only if its script parses — mending it first if that is all it needs.

    Banking a broken page is worse than banking nothing: the reader sees progress kept, and
    every run that resumes from it is rejected by the render check before it starts."""
    good = mend_page(page)
    if good is None:
        log_run(code, "refused to write a page that does not parse", file=os.path.basename(path))
        return None
    if good is not page:
        log_run(code, "mended a broken string literal before writing",
                file=os.path.basename(path))
    open(path, "w", encoding="utf-8").write(good)
    return good


def repair_page(base, table, code, budget=60):
    """Find the translations that break the page, drop them, keep the rest.

    A pass used to be thrown away whole when one translation of two hundred broke the
    script — the reader saw the language go back to `NN% — finish` and nothing to show for
    four minutes of work. The offender is found by removal (drop half, ask node again),
    which is a handful of syntax checks rather than a re-translation."""
    node = shutil.which("node")
    if not node:
        return None
    def without(rm):
        page, _ = apply_table(base, {k: v for k, v in table.items() if k not in rm}, code)
        return page
    spent = [0]
    def clean(rm):
        spent[0] += 1
        return spent[0] <= budget and js_parses(without(rm), node)
    def hunt(cand, also):
        """Narrow `cand` (removing cand+also parses) down to the guilty keys."""
        if len(cand) == 1 or spent[0] >= budget:
            return list(cand)
        h = len(cand) // 2
        a, b = cand[:h], cand[h:]
        if clean(set(a) | set(also)):
            return hunt(a, also)
        if clean(set(b) | set(also)):
            return hunt(b, also)
        return hunt(a, list(also) + b) + hunt(b, list(also) + a)
    keys = sorted(table, key=len, reverse=True)
    if not clean(set(keys)):
        return None                          # not the translations — something else is wrong
    bad = hunt(keys, [])
    if not bad or spent[0] > budget:
        return None
    kept = {k: v for k, v in table.items() if k not in set(bad)}
    page, replaced = apply_table(base, kept, code)
    if not js_parses(page, node):
        return None
    return page, kept, replaced, bad


def render_problems(out, code, table, replaced):
    """Everything that would make a rendered page unfit to keep."""
    problems = []
    node = shutil.which("node")
    if node and not js_parses(out, node):
        detail = ""
        try:
            import tempfile
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                             encoding="utf-8") as fh:
                fh.write(js_span(out)); js_path = fh.name
            chk = subprocess.run([node, "--check", js_path],
                                 capture_output=True, text=True, timeout=60)
            os.unlink(js_path)
            lines = (chk.stderr or "").strip().split("\n")
            detail = next((l for l in lines if "Error" in l), lines[0] if lines else "")
        except Exception:
            pass
        problems.append("the translated page does not parse: %s" % detail[:200])
    if replaced < len(table) * 0.9:
        problems.append("only %d of %d translations could be substituted" % (replaced, len(table)))
    if "</html>" not in out[-2000:]:
        problems.append("output is truncated")
    if "CURRENT_LANG='%s'" % code not in out:
        problems.append("CURRENT_LANG was not set")
    for probe in (">Overview<", ">Process Step-by-Step<", ">Process Challenges<",
                  ">Terminology<"):
        if probe in out:
            problems.append("tab label still English: %s" % probe.strip("<>"))
    return problems


def apply_table(base, table, code):
    """Substitute a dictionary into the page, longest string first."""
    out, replaced = base, 0
    for s in sorted(table, key=len, reverse=True):
        out, hits = substitute(out, s, table[s])
        if hits:
            replaced += 1
    out = re.sub(r"const CURRENT_LANG='[a-z]{2}'", "const CURRENT_LANG='%s'" % code, out)
    return out, replaced


def salvage(base, slices, results, code):
    """What the batches that DID land are worth, as `{"salvage": page}` or nothing.

    A pass used to be all-or-nothing: one failed batch, or a stop, and every batch that had
    already come back was dropped on the floor — which is how a run at 48% left no trace and
    the row went back to "translate". The batches in hand are a perfectly good partial page.
    """
    table = {}
    for start, chunk in slices:
        got = results.get(start, {})
        for k, s in enumerate(chunk):
            v = fit_to_source(s, got.get(start + 1 + k))
            if v and v != s:
                table[s] = v
    if not table:
        return {}
    out, replaced = apply_table(base, table, code)
    return {"salvage": out, "salvaged": replaced} if replaced else {}


def translate_pass(exe, workdir, code, topic, base, strings, state, strict):
    """One dictionary-then-substitute pass over `strings`, applied on top of `base`.

    Returns (out, table, missing, replaced), or an error dict. `strict` belongs to a
    first full render, where most strings coming back unchanged means the model failed.
    A top-up pass is never strict: what is still English after a render is largely
    names, codes and terms of art that are meant to read the same in every language.

    `identical` is the part of `missing` the model answered and answered with the same
    text — it asked for the string and kept it. That is a decision, not a failure, and
    it is what lets a page be called finished."""
    table, missing, identical = {}, [], []
    # A render is minutes of silence otherwise. Count the strings as their batch lands,
    # so the page can say how much of the work is done rather than only how long it
    # has been waiting.
    state["total"] = len(strings)
    state["done"] = 0
    # Batches are independent, so run a few at once — one call per 80 strings, three
    # in flight. Sequential 60-string batches made a page take the best part of ten
    # minutes; this brings it under two.
    BATCH, WORKERS = 80, 3
    slices = [(s, strings[s:s + BATCH]) for s in range(0, len(strings), BATCH)]
    results, failures, lost = {}, [], 0
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(translate_chunk, exe, workdir, code, topic,
                               chunk, start + 1, state): (start, chunk)
                   for start, chunk in slices}
        for fut in cf.as_completed(futures):
            start, chunk = futures[fut]
            try:
                results[start] = fut.result()
            except Cancelled:
                for f in futures:
                    f.cancel()
                return dict({"error": "cancelled"}, **salvage(base, slices, results, code))
            except Exception as e:
                # One batch answering badly is not a reason to throw away the rest of the
                # page: let the others land, and leave these strings for the next pass.
                failures.append("strings %d-%d: %s" % (start + 1, start + len(chunk), e))
                lost += len(chunk)
                log_run(code, "batch %d-%d gave up — its strings go to the next pass"
                        % (start + 1, start + len(chunk)), detail=str(e)[:160])
            state["done"] = state.get("done", 0) + len(chunk)
    if failures and not results:
        return dict({"error": "batch-failed", "detail": "; ".join(failures)[:300]},
                    **salvage(base, slices, results, code))
    if state["cancel"]:
        return dict({"error": "cancelled"}, **salvage(base, slices, results, code))
    state["phase"] = "substituting"
    for start, chunk in slices:
        got = results.get(start, {})
        for k, s in enumerate(chunk):
            raw = got.get(start + 1 + k)
            v = fit_to_source(s, raw)
            if v and v != s:
                table[s] = v
            else:
                missing.append(s)
                if v == s or (isinstance(raw, str) and raw.strip() == s):
                    identical.append(s)          # answered, and deliberately unchanged
    answered = max(1, len(strings) - lost)
    if strict and len(table) < answered * 0.75:
        return {"error": "translation-incomplete",
                "detail": "%d of %d strings came back translated; first missed: %s"
                          % (len(table), answered, "; ".join(missing[:3]))}
    out, replaced = apply_table(base, table, code)
    return out, table, missing, replaced, identical, failures


def kept_path(workdir, code):
    return os.path.join(workdir, "index.%s.kept.json" % code)


def load_kept(workdir, code):
    """Strings the translator was asked about and deliberately left in English.

    Without this record a page can never be finished: aviation terms of art, regulation
    names and people's names are meant to read the same in every language, so they sit
    in the page as English forever and hold the score below 100% no matter how many
    times they are sent out again."""
    try:
        data = json.load(open(kept_path(workdir, code), encoding="utf-8"))
        return set(data.get("kept", [])) if isinstance(data, dict) else set()
    except Exception:
        return set()


def save_kept(workdir, code, kept):
    try:
        json.dump({"kept": sorted(kept)}, open(kept_path(workdir, code), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    except Exception:
        pass


def translate(exe, workdir, code, topic="a business process"):
    """Bring a language to a finished page, translating only what is still English.

    The CLI never rewrites the page: it translates a numbered list of strings and the
    bridge substitutes them, so the HTML and JavaScript structure cannot be damaged and
    completeness is countable rather than hoped for.

    A page that already exists is not discarded and redone. The strings still verbatim
    English in it are the only ones sent out, and the result is applied on top — so a
    render interrupted at 60%, or a first pass that landed at 97%, is finished instead
    of repeated. Each pass shrinks the remaining list; passes stop when the page is
    complete, when a pass changes nothing, or at MAX_PASSES."""
    if code not in LANGS:
        return {"error": "unknown-language"}
    target = "index.html" if code == "en" else "index.%s.html" % code
    path = os.path.join(workdir, target)
    partial = path + ".partial"
    src = os.path.join(workdir, "index.html")
    if not os.path.isfile(src):
        return {"error": "no-source-page"}
    if code == "en":
        return {"file": target, "cached": True, "coverage": 1.0}
    job = (os.path.realpath(workdir), code)
    if _translating.get(job):
        log_run(code, "asked again while already running — left alone")
        return {"error": "already-running"}

    # What is already translated — the rendered page, or the partial an interrupted run left.
    # Ignoring the partial made a resumed run report 0% to the page and to the log while it
    # was in fact carrying on from 52%, so the row appeared to have thrown that away.
    started = translation_coverage(workdir, code)
    if started == 0.0 and not os.path.isfile(path) and os.path.isfile(partial):
        started = translation_coverage(workdir, code, partial)
    if os.path.isfile(path) and started >= COMPLETE:
        return {"file": target, "cached": True, "coverage": started}

    state = {"cancel": False, "procs": [], "phase": "reading", "t0": time.time(),
             "total": 0, "done": 0, "pass": 0, "passes": MAX_PASSES,
             "coverage": started}
    _translating[job] = state
    try:
        english = open(src, encoding="utf-8").read()
        allstr = extract_strings(english)
        if not allstr:
            return {"error": "nothing-to-translate"}

        # Build on the page as far as it got — the rendered file, or the progress an
        # interrupted run left behind — and only fall back to English for a first render.
        base_path = path if os.path.isfile(path) else (partial if os.path.isfile(partial) else None)
        out = open(base_path, encoding="utf-8").read() if base_path else english
        first = base_path is None
        if not first:
            # A page banked before this check existed can itself be broken; then every pass
            # on top of it is rejected and the language can never finish. Mend it, or start
            # from English rather than inheriting the fault.
            good = mend_page(out)
            if good is None:
                log_run(code, "the page we resumed from does not parse — starting from English",
                        file=os.path.basename(base_path))
                out, first, started = english, True, 0.0
                state["coverage"] = 0.0
            elif good is not out:
                out = good
                log_run(code, "mended the page we resumed from", file=os.path.basename(base_path))
        log_run(code, "translating", strings=len(allstr),
                resuming_from="%d%%" % round(started * 100) if started else None,
                base=os.path.basename(base_path) if base_path else "the English page")

        kept = load_kept(workdir, code)
        cov, passes, translated, replaced_total, left = started, 0, 0, 0, 0
        limit, retried = MAX_PASSES, 0
        while passes < limit:
            strings = allstr if (first and passes == 0) else [s for s in allstr if s in out]
            left = len(strings)
            if not strings:
                break
            state["pass"] = passes + 1
            state["phase"] = "translating"
            log_run(code, "pass %d starting" % (passes + 1), strings=left,
                    at="%d%%" % round(cov * 100))
            res = translate_pass(exe, workdir, code, topic, out, strings, state,
                                 strict=(first and passes == 0))
            if isinstance(res, dict):                 # a pass failed or was cancelled
                # The batches that landed before it broke are worth keeping: bank them as the
                # partial so the next attempt carries on from there instead of from nothing.
                salv = res.get("salvage")
                if isinstance(salv, str) and salv != out:
                    out = salv
                    cov = coverage_between(english, out, kept)
                    state["coverage"] = cov
                    if cov > started:
                        try:
                            if write_page(partial, out, code, "partial") is None:
                                raise RuntimeError("would not parse")
                            res = dict(res, coverage=cov, kept_progress=True)
                            log_run(code, "kept the part that landed", at="%d%%" % round(cov * 100),
                                    strings=res.get("salvaged"), file=os.path.basename(partial))
                        except Exception as e:
                            log_run(code, "could not write the partial", error=e)
                log_run(code, "pass %d ended: %s" % (passes + 1, res.get("error")),
                        detail=str(res.get("detail", ""))[:160], at="%d%%" % round(cov * 100))
                if passes == 0:
                    return res                        # nothing more earned — report it
                break                                 # keep what earlier passes achieved
            cand, table, missing, replaced, identical, failures = res
            state["phase"] = "checking"
            problems = render_problems(cand, code, table, replaced)
            if problems and any("does not parse" in x for x in problems):
                # One translation in two hundred can break the script, and throwing the
                # whole pass away for it is what the reader sees as "nothing happened".
                # Find it, drop it, keep everything else.
                state["phase"] = "repairing"
                fixed = repair_page(out, table, code)
                if fixed:
                    cand, table, replaced, bad = fixed
                    missing.extend(bad)
                    log_run(code, "pass %d repaired" % (passes + 1),
                            dropped=len(bad), example=str(bad[0])[:60] if bad else "")
                    problems = render_problems(cand, code, table, replaced)
                else:
                    try:
                        keep = os.path.join(workdir, ".chat-bridge-reject-%s.html" % code)
                        open(keep, "w", encoding="utf-8").write(cand)
                        problems.append("the rejected page is in %s" % os.path.basename(keep))
                    except Exception:
                        pass
            if problems:
                log_run(code, "pass %d rejected by the render check" % (passes + 1),
                        detail="; ".join(problems)[:200], at="%d%%" % round(cov * 100))
                if passes == 0:
                    return {"error": "validation-failed", "detail": "; ".join(problems)}
                break                                 # keep the last good page instead
            passes += 1
            out = cand
            translated += len(table); replaced_total += replaced
            kept |= set(identical)
            cov = coverage_between(english, out, kept)
            state["coverage"] = cov
            # Bank the ground gained now, so a later stumble cannot cost it, and the run
            # carries straight on into the next pass — a batch that broke is retried here
            # rather than left for the reader to notice and click again.
            if failures:
                log_run(code, "pass %d partial — %d batch(es) failed, carrying on"
                        % (passes, len(failures)), detail="; ".join(failures)[:160],
                        at="%d%%" % round(cov * 100))
                if cov > started and cov < COMPLETE:
                    try:
                        write_page(partial, out, code, "partial")
                    except Exception as e:
                        log_run(code, "could not write the partial", error=e)
                if retried < EXTRA_PASSES and table:
                    limit += 1
                    retried += 1
            if cov >= COMPLETE or not table:
                break
        if state["cancel"]:
            if cov > started and out != english:
                try:
                    write_page(partial, out, code, "partial")
                    log_run(code, "stopped — kept what was done", at="%d%%" % round(cov * 100))
                except Exception as e:
                    log_run(code, "stopped, but could not write the partial", error=e)
            else:
                log_run(code, "stopped with nothing to keep")
            return {"error": "cancelled", "coverage": cov}

        state["phase"] = "saving"
        if kept:
            save_kept(workdir, code, kept)
        if cov >= MIN_COVERAGE:
            if write_page(path, out, code, "page") is None:
                return {"error": "validation-failed",
                        "detail": "the finished page does not parse; nothing was written"}
            if os.path.isfile(partial):
                os.remove(partial)
            log_run(code, "finished", at="%d%%" % round(cov * 100), passes=passes, file=target)
            register_language(workdir, code, LANGS_LABEL.get(code, LANGS[code]), target)
            return {"file": target, "cached": False, "coverage": cov, "started": started,
                    "passes": passes, "strings": len(allstr), "translated": translated,
                    "substituted": replaced_total, "remaining": left, "kept": len(kept)}
        # Short of usable, but the work is not thrown away: the next attempt continues
        # from here instead of starting the whole page again.
        write_page(partial, out, code, "partial")
        if os.path.isfile(path):
            os.remove(path)
        log_run(code, "short of usable — progress kept", at="%d%%" % round(cov * 100),
                passes=passes, file=os.path.basename(partial))
        return {"error": "translation-incomplete", "coverage": cov, "passes": passes,
                "detail": "%d%% of the page is translated (was %d%%); the progress was kept — "
                          "pick the language again to carry on from there"
                          % (round(cov * 100), round(started * 100))}
    finally:
        _translating.pop(job, None)


# ---------------------------------------------------------------------------
# The reader's own notes are page content too
#
# Every chat answer is filed as a note, and notes live in the browser rather than
# in the file — so the substitute-into-the-HTML machinery above can never reach
# them, and a reader switching to Italian kept an Italian page with English notes.
# They are translated the same way everything else is: a numbered list out, a
# dictionary back, cached per language. The cache lives with the note (the page
# writes it into localStorage), so a language is translated once and then simply
# read back.
#
# The note keeps its own text as written. A translation is an added view of it,
# never a replacement — losing the reader's own words to a language switch would
# be unforgivable.
# ---------------------------------------------------------------------------
NOTE_FIELDS = ("question", "topic", "concept", "why", "example", "answer")


def translate_notes(exe, workdir, code, topic, notes):
    """Translate a reader's notes into one language. Returns {id: {field: text}}.

    Nothing is written to disk: the notes belong to the browser that holds them, and
    the page caches what comes back. Fields that are empty, or that came back
    unchanged, are simply absent from the answer — the page falls back to the note as
    it was written."""
    if code not in LANGS:
        return {"error": "unknown-language"}
    if not isinstance(notes, list) or not notes:
        return {"error": "no-notes"}

    # One flat list of strings, so a notebook costs one call per 80 fields rather
    # than one call per note.
    lines, where = [], []
    for note in notes[:400]:
        if not isinstance(note, dict):
            continue
        nid = str(note.get("id", ""))[:64]
        if not nid:
            continue
        for field in NOTE_FIELDS:
            val = note.get(field)
            if isinstance(val, str) and val.strip():
                lines.append(val.strip()); where.append((nid, field))
    if not lines:
        return {"error": "no-notes"}

    state = {"cancel": False, "procs": []}
    table = {}
    BATCH, WORKERS = 80, 3
    slices = [(s, lines[s:s + BATCH]) for s in range(0, len(lines), BATCH)]
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(translate_chunk, exe, workdir, code, topic,
                               chunk, start + 1, state): (start, chunk)
                   for start, chunk in slices}
        for fut in cf.as_completed(futures):
            start, chunk = futures[fut]
            try:
                got = fut.result()
            except Cancelled:
                return {"error": "cancelled"}
            except Exception as e:
                return {"error": "batch-failed", "detail": str(e)[:300]}
            for k, _ in enumerate(chunk):
                v = got.get(start + 1 + k)
                if isinstance(v, str) and v.strip():
                    table[start + k] = v.strip()

    out = {}
    for i, (nid, field) in enumerate(where):
        v = table.get(i)
        if v and v != lines[i]:
            out.setdefault(nid, {})[field] = v
    if not out:
        return {"error": "nothing-to-translate"}
    return {"lang": code, "notes": out,
            "fields": sum(len(v) for v in out.values()), "asked": len(lines)}


PROMPT = """You are the industry-expert agent for this process exploration.

Process:  {process}
Industry: {industry}
Company:  {company}

The reader is on the "{section}" screen, looking at "{item}". Their question:

{question}

Ground truth, in order: content.md in this directory, then research/*.md, then
context/extracted.md if it exists — that one is the customer's own material and
outranks everything, including your own knowledge. Read what you need. Reuse the
running example already in content.md (same order number, amounts, dates). Never
invent a figure; if none is sourced, describe the mechanism instead.

Answer as a practitioner explaining to someone who has never run this process.
**Write every field in {language}** — that is the language the reader has this page open
in, and the answer is filed into their notes as it stands. Keep company, product and
place names, codes and terms of art in their usual form.

**One note per concept.** Split the question into the distinct concepts it actually
asks about and return one note for each — never one note covering several. A reader who
asked about three things wants three notes they can find separately later, not one long
note they must re-read to use. Two concepts are distinct when a reader could need one
without the other; if the question really asks about one thing, return one note. At most 5 —
beyond that, cover the ones the reader is standing closest to.

**A note is two things: the explanation, and the example. Nothing else.**
- `what` is the explanation — **exactly what they asked, in two or three short sentences, 55
  words at the outside**. No history, no second concept, no restating the question, no ground
  the reader did not ask for.
- `example` is the worked case, as structured lines (below).
- **There is no `why` field. Do not send one**, and do not smuggle a "why it matters"
  paragraph into `what` as extra sentences — the reader asked to understand the thing, not to
  be told it is important. If the consequence is genuinely part of the answer, it is the last
  clause of a sentence, not a section.
- The whole note runs about **90 words, never past 120**. Verbosity is the failure mode: it is
  a note read in a hurry, not an essay.

**The example is structured, not a paragraph.** Three to five short lines, separated by real
newlines inside the JSON string, each one a label and its value, the last line stating the
effect:

    Standard: material 100234, plant 1100, lot size 5,000 kg, EUR 150 setup -> EUR 0.03/kg
    Order:    900045678, 4,000 kg planned, 3,850 kg good output
    Effect:   EUR 150 over 3,850 kg = EUR 0.039/kg -> EUR 0.009/kg lot size variance

Label the lines in {language}. Use the running example from content.md (same order number,
amounts, dates); no figure you cannot source — describe the mechanism instead. Never a line
that only restates the definition, and no term inside it the note has not explained. 60 words
for the whole example.

Return ONLY this JSON object, no prose and no code fence — two content fields, no `why`:
{{"notes":[{{"topic":"short noun phrase","what":"…","example":"…"}}]}}"""


# A reader can now select a whole paragraph, not just a phrase — the question is often about
# how several sentences fit together, and the page no longer refuses that. The wording above is
# written for a phrase, so a passage gets this correction appended: same one-note contract, but
# `topic` must be a label the expert writes rather than the passage echoed back.
LONG_SELECTION = """
Note: this selection is a **passage of several sentences, not a phrase**. Answer it as one
question about the passage as a whole — what it is really saying, and the part of it the reader
is most likely to have stumbled on — rather than glossing each sentence in turn. `topic` must be
a short label **of your own** naming what the passage is about; the passage itself would be an
unreadable heading in their notebook. Everything else above still holds: exactly one note.
"""

SELECTION_PROMPT = """

The reader did not type this question — they **selected a phrase on the page**:

    "{selection}"

and asked for {want}.
{detail}
So: **return exactly ONE note**, about that phrase and nothing else. A selected phrase is
one concept by definition; splitting it would invent concepts the reader never asked
about, and each note is filed separately in their notebook. Set `topic` to the phrase
itself, or to the smallest noun phrase that names it — it becomes the note's heading and
the reader has to recognise it as the thing they selected.

{emphasis}

Explain the phrase as it is used *here*, in this process at this company — not the
dictionary sense. If the phrase is a term of art the surrounding text already defines
differently, follow the page."""

WANT = {"explain": "an explanation of it",
        "example": "an example that makes it concrete"}

# What the reader typed into the bar, when they typed anything. This is the most specific
# thing in the whole request: the phrase says WHAT they are looking at, the mode says which
# kind of help they want, and this says which part actually lost them. It therefore outranks
# both — an answer that explains the phrase correctly but not the part they asked about has
# missed. When the field was left empty the request is simply the phrase, and nothing about
# the prompt should imply the reader failed to say more.
# The reader can aim a refinement at ONE block of the note — its explanation, its example,
# or an earlier follow-up — by clicking the control on that block instead of the one on the
# note. When they do, they have already told us what they are looking at, and the answer must
# stay inside it: rewriting the example when they asked about the explanation is the failure
# this exists to prevent.
REFINE_PART = """
They asked this about **one part of the note in particular — the {part}**. That part currently
reads:

    {focus}

Improve **that part, and only that part**. Do not answer for the rest of the note: the reader
kept the rest, and a follow-up that revisits it buries the piece they asked for.
"""

REFINE_PROMPT = """

This is a **follow-up on a note the reader already has**. They read it, and one thing in it
is still not clear. Here is the note, so you answer in the context of what they have already
been told rather than starting over:

    Topic:        {topic}
    They asked:   {question}
    Explanation:  {what}
    Also said:    {why}
    Example:      {example}

What they want explained better:

    "{ask}"
{part}
**Return exactly ONE note**, and treat it as the missing piece rather than a rewrite:
- Do **not** restate what the note above already says. They have read it. If the honest
  answer is that the note was already right, say what they seem to be reading differently
  and correct that instead.
- Answer only the thing they asked about, in **two or three short sentences** in `what`.
  **Send no `why`.** Add an `example` only when it genuinely helps; leave it empty otherwise —
  a padded follow-up buries the one thing they were waiting for. An example here is the same
  structured lines, label and value, ending on the effect.
- Where an example helps, prefer extending the note's own example (same numbers, same
  order) over inventing a second one, so their notebook keeps one running case.
- `topic` is a short label for the follow-up, not a repeat of the note's topic.

"""


DETAIL = """
They also said, in their own words, what they want cleared up:

    "{detail}"

**Answer that.** It is more specific than either the phrase or the mode, so it decides what
the note is about: lead with it, and leave out the parts of the phrase they did not ask
about. If what they typed turns out to be a different question that merely starts from the
phrase, follow their question — they can see the phrase, and they told you what they need.
"""
EMPHASIS = {
    "explain": "They asked to understand it, so `what` carries the answer: what the phrase "
               "means in this process, in two or three sentences. `example` still has to be "
               "there, and still has to be a real situation.",
    "example": "They asked for an example, so `example` carries the answer — the same "
               "structured lines, label and value, ending on the effect, in the running "
               "case from content.md. Keep `what` to ONE sentence; it is the frame, not the "
               "answer, and a long frame buries the example.",
}


def claude_path():
    return shutil.which("claude")


def claude_version(exe):
    try:
        return subprocess.run([exe, "--version"], capture_output=True, text=True,
                              timeout=20).stdout.strip()
    except Exception:
        return ""


def unescape_too_much(text):
    """Undo the over-escaping a careful model does: `\\\\"` where `\\"` was meant.

    Seen for real (`.chat-bridge-batch-it-81.txt`, 14 September): a batch of eighty strings came
    back with `si leggono entrambi \\\\"150 kg\\\\"` inside a value — JSON reads that as a literal
    backslash followed by the closing quote, so the object stops parsing mid-string and eighty
    good translations were thrown away. The prompt asks for `\\n` to be preserved, and a model
    escaping conscientiously escapes the quotes too. Trying the un-escaped reading costs nothing:
    it is used only when the strict one has already failed."""
    return re.sub(r'\\{2,}"', '\\\\"', text)


def extract_json(text):
    """The CLI may wrap the object in prose or a fence; take the first {...} block.

    Two readings of every candidate: as it came, and with over-escaped quotes repaired."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    for candidate in (text, unescape_too_much(text)):
        try:
            return json.loads(candidate)
        except Exception:
            pass
    depth = start = 0
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                block = text[start:i + 1]
                for candidate in (block, unescape_too_much(block)):
                    try:
                        return json.loads(candidate)
                    except Exception:
                        continue
    return None


def ask_claude(exe, workdir, payload):
    lang = str(payload.get("language", "en")).strip().lower()
    prompt = PROMPT.format(
        process=payload.get("process", "—"), industry=payload.get("industry", "—"),
        company=payload.get("company", "—"), section=payload.get("section", "—"),
        item=payload.get("item", "—"), question=payload.get("question", "").strip(),
        language=LANGS.get(lang, "English"))
    one_note = False
    refine = payload.get("refine")
    if isinstance(refine, dict):
        # A refinement is one focused answer by definition, so it takes the same one-note
        # guarantee a selection does.
        one_note = True
        # A page from before per-part refining sends no `part`; the block is simply omitted
        # and the whole-note wording stands, so an older page keeps working unchanged.
        part = str(refine.get("part", "") or "").strip()[:60]
        focus = str(refine.get("focus", "") or "").strip()[:1600]
        prompt += REFINE_PROMPT.format(
            topic=str(refine.get("topic", "") or "—")[:200],
            question=str(refine.get("question", "") or "—")[:400],
            what=str(refine.get("what", "") or "—")[:1200],
            why=str(refine.get("why", "") or "—")[:1200],
            example=str(refine.get("example", "") or "—")[:1200],
            ask=str(payload.get("question", "") or "").strip()[:400],
            part=REFINE_PART.format(part=part, focus=focus or "—") if part else "")
    selection = str(payload.get("selection", "") or "").strip()
    mode = str(payload.get("mode", "") or "").strip().lower()
    if selection:
        if mode not in WANT:
            mode = "explain"
        one_note = True
        detail = str(payload.get("detail", "") or "").strip()
        # 2000, not 400: the page allows a passage of up to 1500 characters, and truncating
        # the reader's selection mid-sentence would have the expert answer about a fragment
        # while the reader watches for an answer about the paragraph they highlighted.
        prompt += SELECTION_PROMPT.format(
            selection=selection[:2000], want=WANT[mode], emphasis=EMPHASIS[mode],
            detail=DETAIL.format(detail=detail[:400]) if detail else "")
        if len(selection) > 300:
            prompt += LONG_SELECTION
    cmd = [exe, "-p", prompt, "--output-format", "json",
           "--allowedTools", "Read,Grep,Glob"]
    proc = spawn(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                 text=True, cwd=workdir)
    try:
        out, err = proc.communicate(timeout=ASK_TIMEOUT)
    except subprocess.TimeoutExpired:
        stop_tree(proc, signal.SIGKILL); proc.communicate()
        raise
    finally:
        reap(proc)
    if _shutting_down.is_set():
        return {"error": "bridge-stopping"}
    if proc.returncode != 0:
        return {"error": "claude-failed",
                "detail": (err or out or "")[-600:]}
    raw = (out or "").strip()
    try:                                   # --output-format json wraps the reply
        raw = json.loads(raw).get("result", raw)
    except Exception:
        pass
    obj = extract_json(raw if isinstance(raw, str) else json.dumps(raw))
    if not obj:
        return {"error": "unparsable", "detail": str(raw)[:600]}
    notes = as_notes(obj)
    if one_note and len(notes) > 1:
        notes = notes[:1]
    return {"notes": notes}


NOTE_FIELDS = ("topic", "what", "why", "example")
MAX_NOTES = 5


def as_notes(obj):
    """Whatever the CLI returned -> a list of four-field notes.

    The contract asks for {"notes":[…]}, but a model that has just been told to answer
    a question sometimes answers it: a bare object, or a bare list. All three are the
    same intent, and none of them is worth failing a reader's question over. A note with
    nothing in `what` is dropped — an empty card in the notes pane is worse than one
    fewer note."""
    if isinstance(obj, dict):
        raw = obj.get("notes")
        if not isinstance(raw, list):
            raw = [obj]                      # a single note, returned bare
    elif isinstance(obj, list):
        raw = obj
    else:
        return []
    out = []
    for n in raw:
        if not isinstance(n, dict):
            continue
        note = {k: str(n.get(k, "") or "").strip() for k in NOTE_FIELDS}
        if note["what"] or note["why"] or note["example"]:
            out.append(note)
    return out[:MAX_NOTES]


MIN_COVERAGE = 0.90          # below this a language is "incomplete", not "ready"


def coverage_between(english, other, kept=()):
    """How much of `english`'s prose no longer appears verbatim in `other`, 0.0–1.0.

    Terms of art and names are meant to stay identical, so they are excluded from the
    denominator — otherwise a perfect translation would score badly. `kept` carries the
    ones the translator itself decided to leave alone, recorded per language."""
    strings = [s for s in extract_strings(english)
               if len(s.split()) > 2 and s not in KEEP_ALWAYS and s not in kept]
    if not strings:
        return 1.0 if kept else 0.0
    untranslated = sum(1 for s in strings if s in other)
    return round(1.0 - untranslated / len(strings), 4)


def translation_coverage(workdir, code, target=None):
    """How much of the page a rendered language actually translated, 0.0–1.0.

    Compares the strings extracted from the English page against the translated file:
    anything still appearing verbatim was not translated. Terms of art and names are
    meant to stay identical, so they are excluded from the denominator — otherwise a
    perfect translation would score badly.

    `target` measures a file that is not the finished page — the `.partial` an interrupted
    run left behind, which is what makes its progress visible instead of merely resumable."""
    src = os.path.join(workdir, "index.html")
    tgt = target or os.path.join(workdir,
                                 "index.html" if code == "en" else "index.%s.html" % code)
    if code == "en" and not target:
        return 1.0
    if not (os.path.isfile(src) and os.path.isfile(tgt)):
        return 0.0
    try:
        english = open(src, encoding="utf-8").read()
        other = open(tgt, encoding="utf-8").read()
    except Exception:
        return 0.0
    return coverage_between(english, other, load_kept(workdir, code))


def languages_on_disk(workdir, min_coverage=MIN_COVERAGE):
    """What is rendered on disk: ready codes, unfinished ones, and each one's coverage."""
    ready, partial, coverage = [], {}, {}
    if os.path.isfile(os.path.join(workdir, "index.html")):
        ready.append("en"); coverage["en"] = 1.0
    for name in sorted(os.listdir(workdir)) if os.path.isdir(workdir) else []:
        m = re.fullmatch(r"index\.([a-z]{2})\.html", name)
        if not m:
            continue
        code = m.group(1)
        cov = translation_coverage(workdir, code)
        coverage[code] = cov
        if cov >= min_coverage:
            ready.append(code)
        else:
            partial[code] = cov          # exists, but not offered as ready
    # A run the bridge could not finish leaves index.<code>.html.partial. translate() already
    # resumes from it; reporting it here is what lets the menu SAY so — "32% — finish" instead
    # of "translate", which is the difference between banked work and work the reader thinks
    # they lost.
    for name in sorted(os.listdir(workdir)) if os.path.isdir(workdir) else []:
        m = re.fullmatch(r"index\.([a-z]{2})\.html\.partial", name)
        if not m:
            continue
        code = m.group(1)
        if code in ready or code in partial:
            continue                     # a finished file always outranks its leftovers
        cov = translation_coverage(workdir, code, os.path.join(workdir, name))
        if cov > 0:
            partial[code] = coverage[code] = cov
    return ready, partial, coverage


SLUG_OK = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def library_root(workdir):
    return os.path.dirname(os.path.realpath(workdir))


_SIBLINGS_CACHE = {}              # root -> (expires_at, payload); coverage costs a full read


def siblings(workdir):
    """The other explorations sitting in this bridge's library.

    A bridge is started in one directory but a library holds many, and every page in
    it reaches for whichever bridge is up. Serving its siblings too is what stops a
    page from being told to start a second bridge for the folder next door."""
    root, mine, out = library_root(workdir), os.path.realpath(workdir), {}
    hit = _SIBLINGS_CACHE.get(root)
    if hit and hit[0] > time.time():
        return hit[1]
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        d = os.path.join(root, name)
        if not SLUG_OK.match(name) or os.path.realpath(d) == mine:
            continue
        if not os.path.isfile(os.path.join(d, "index.html")):
            continue
        ready, partial, coverage = languages_on_disk(d)
        out[name] = {"languages": ready, "partial": partial, "coverage": coverage}
    _SIBLINGS_CACHE[root] = (time.time() + 15, out)
    return out


def resolve_workdir(workdir, slug):
    """The directory a request means: this bridge's own, or a named sibling.

    Refuses anything that is not a plain sibling name holding an index.html, so a
    request can never write outside the library."""
    slug = str(slug or "").strip()
    if not slug or slug == os.path.basename(os.path.realpath(workdir)):
        return workdir
    if not SLUG_OK.match(slug):
        return None
    d = os.path.join(library_root(workdir), slug)
    if os.path.realpath(os.path.dirname(os.path.realpath(d))) != library_root(workdir):
        return None
    return d if os.path.isfile(os.path.join(d, "index.html")) else None


LAST_SEEN = [time.time()]         # mtime of the most recent request, for the reaper


class Handler(BaseHTTPRequestHandler):
    server_version = "ProcessExplorationBridge/1"

    def handle_one_request(self):
        LAST_SEEN[0] = time.time()
        return BaseHTTPRequestHandler.handle_one_request(self)

    def log_message(self, fmt, *a):          # one tidy line per request
        sys.stderr.write("  %s\n" % (fmt % a))

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        try:
            self._send_unsafe(code, body)
        except (BrokenPipeError, ConnectionResetError):
            pass          # the page navigated away or was closed — nothing to report

    def _send_unsafe(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        route = urlparse(self.path).path.rstrip("/") or "/"
        # Every translation running for this exploration, whoever started it. A page that
        # reloads mid-run has an empty JOBS map and would otherwise offer "translate" for a
        # language that is being translated right now; this is how it finds out.
        if route == "/jobs":
            q = parse_qs(urlparse(self.path).query)
            where = resolve_workdir(self.server.workdir, (q.get("exploration", [""])[0]))
            if where is None:
                return self._send(404, {"error": "unknown-exploration"})
            real = os.path.realpath(where)
            running = {}
            for (wd, code), st in list(_translating.items()):
                if wd != real:
                    continue
                total, done = st.get("total", 0) or 0, st.get("done", 0) or 0
                running[code] = {"running": True, "phase": st.get("phase", ""),
                                 "total": total, "done": min(done, total),
                                 "pass": st.get("pass", 0), "passes": st.get("passes", 0),
                                 "coverage": st.get("coverage", 0),
                                 "cancelling": bool(st.get("cancel")),
                                 "elapsed": job_elapsed(st)}
            return self._send(200, {"running": running})
        if route == "/progress":
            q = parse_qs(urlparse(self.path).query)
            code = (q.get("lang", [""])[0] or "").lower()
            where = resolve_workdir(self.server.workdir, (q.get("exploration", [""])[0]))
            if where is None:
                return self._send(404, {"error": "unknown-exploration"})
            st = _translating.get((os.path.realpath(where), code))
            if not st:
                return self._send(200, {"running": False})
            total, done = st.get("total", 0) or 0, st.get("done", 0) or 0
            return self._send(200, {"running": True, "phase": st.get("phase", ""),
                                    "total": total, "done": min(done, total),
                                    "pass": st.get("pass", 0), "passes": st.get("passes", 0),
                                    "coverage": st.get("coverage", 0),
                                    "cancelling": bool(st.get("cancel")),
                                    "elapsed": job_elapsed(st)})
        if route != "/health":
            return self._send(404, {"error": "not-found"})
        exe = claude_path()
        workdir = self.server.workdir
        # A bridge is only usable if the page it serves is still on disk. Saying
        # ok:true for a deleted directory is how a defunct bridge kept the lowest
        # port and swallowed every request the page sent it.
        usable = os.path.isfile(os.path.join(workdir, "index.html"))
        ready, partial, coverage = languages_on_disk(workdir) if usable else ([], {}, {})
        self._send(200, {"ok": usable, "usable": usable, "claude": bool(exe),
                         "version": claude_version(exe) if exe else "",
                         "dir": workdir, "reason": "" if usable else "no-source-page",
                         "languages": ready, "partial": partial, "coverage": coverage,
                         "complete": COMPLETE,
                         "beat": BEAT_EVERY if _autoexit else 0,
                         "library": library_root(workdir),
                         "siblings": siblings(workdir) if usable else {}})

    def _sid(self):
        """Read the session id out of the body — sendBeacon sends text/plain."""
        try:
            n = min(int(self.headers.get("Content-Length") or 0), MAX_BODY)
            body = self.rfile.read(n) or b"{}"
            return str(json.loads(body).get("sid", "")).strip()[:64]
        except Exception:
            return ""

    def do_POST(self):
        route = self.path.rstrip("/")
        if route == "/beat":
            note_beat(self._sid())
            return self._send(200, {"ok": True, "beat": BEAT_EVERY if _autoexit else 0})
        if route == "/bye":
            note_bye(self._sid())
            if not _autoexit:
                return self._send(200, {"ok": True, "stopping": False})
            # Do not answer with a promise we may not keep: whether we actually stop
            # is decided BYE_GRACE seconds from now, by whether anything beats again.
            return self._send(200, {"ok": True, "stopping": True})
        if route == "/translate/cancel":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                code = str(body.get("lang", "")).lower()
                where = resolve_workdir(self.server.workdir, body.get("exploration"))
            except Exception:
                code, where = "", self.server.workdir
            if where is None:
                return self._send(200, {"cancelled": False, "reason": "unknown-exploration"})
            state = _translating.get((os.path.realpath(where), code))
            if not state:
                return self._send(200, {"cancelled": False, "reason": "not-running"})
            state["cancel"] = True
            for proc in list(state.get("procs", [])):
                stop_tree(proc, signal.SIGTERM)
            return self._send(200, {"cancelled": True})
        if route not in ("/ask", "/translate", "/translate/notes"):
            return self._send(404, {"error": "not-found"})
        exe = claude_path()
        if not exe:
            return self._send(503, {"error": "no-claude"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > (NOTES_BODY if route == "/translate/notes" else MAX_BODY):
                return self._send(413, {"error": "too-large"})
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, {"error": "bad-json"})
        if route == "/translate/notes":
            code = str(payload.get("lang", "")).strip().lower()
            topic = str(payload.get("topic", "a business process"))[:120]
            where = resolve_workdir(self.server.workdir, payload.get("exploration"))
            if where is None:
                return self._send(404, {"error": "unknown-exploration"})
            try:
                return self._send(200, translate_notes(exe, where, code, topic,
                                                       payload.get("notes")))
            except subprocess.TimeoutExpired:
                return self._send(504, {"error": "timeout"})
            except Exception as e:
                return self._send(500, {"error": "bridge-failed", "detail": str(e)[:400]})
        if route == "/translate":
            code = str(payload.get("lang", "")).strip().lower()
            topic = str(payload.get("topic", "a business process"))[:120]
            where = resolve_workdir(self.server.workdir, payload.get("exploration"))
            if where is None:
                return self._send(404, {"error": "unknown-exploration"})
            try:
                return self._send(200, translate(exe, where, code, topic))
            except subprocess.TimeoutExpired:
                return self._send(504, {"error": "timeout"})
            except Exception as e:
                return self._send(500, {"error": "bridge-failed", "detail": str(e)[:400]})
        if not str(payload.get("question", "")).strip():
            return self._send(400, {"error": "empty-question"})
        with _asking_lock:
            _asking[0] += 1
        try:
            self._send(200, ask_claude(exe, self.server.workdir, payload))
        except subprocess.TimeoutExpired:
            self._send(504, {"error": "timeout"})
        except Exception as e:
            self._send(500, {"error": "bridge-failed", "detail": str(e)[:400]})
        finally:
            with _asking_lock:
                _asking[0] -= 1


def reaper(workdir, port):
    """Retire this bridge when it stops being useful.

    Two conditions, both cheap to check: the exploration it serves has been deleted
    (so it can only ever answer no-source-page), or nothing has asked it anything in
    IDLE_EXIT. Either way it frees its port instead of outliving its purpose."""
    import threading

    def loop():
        gone = 0
        while True:
            time.sleep(REAP_EVERY)
            if not os.path.isfile(os.path.join(workdir, "index.html")):
                gone += 1
                if gone >= 3:            # tolerate a transient rename or a rewrite
                    print("! source page gone from %s - retiring this bridge" % workdir,
                          file=sys.stderr, flush=True)
                    clear_portfile(workdir)
                    os._exit(0)
                continue
            gone = 0
            if time.time() - LAST_SEEN[0] > IDLE_EXIT and not _translating:
                print("! idle for %dh - retiring this bridge" % (IDLE_EXIT // 3600),
                      file=sys.stderr, flush=True)
                clear_portfile(workdir)
                os._exit(0)

    threading.Thread(target=loop, daemon=True).start()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".", help="the exploration directory to answer from")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--selftest", action="store_true",
                    help="check the CLI and the JSON extractor, then exit")
    ap.add_argument("--keep-alive", action="store_true",
                    help="stay up after the page is closed (default: shut down with it)")
    a = ap.parse_args()
    global _autoexit
    _autoexit = not a.keep_alive
    workdir = os.path.abspath(os.path.expanduser(a.dir))

    if a.selftest:
        exe = claude_path()
        print("claude on PATH:", exe or "NO")
        if exe:
            print("version:", claude_version(exe))
        probe = 'here you go:\n```json\n{"topic":"t","what":"w","why":"y","example":"e"}\n```'
        print("extractor:", extract_json(probe))
        ready, partial, coverage = languages_on_disk(workdir)
        print("languages ready:", ready, "| incomplete:", partial)
        print("coverage:", ", ".join("%s %d%%" % (c, round(v * 100))
                                     for c, v in sorted(coverage.items())) or "none")
        return 0 if exe else 1

    if not claude_path():
        print("! no `claude` on PATH — the page will show “no Claude in this environment”",
              file=sys.stderr)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    srv.workdir = workdir
    reaper(workdir, a.port)
    try:                                  # so library.sh can find this bridge directly
        open(os.path.join(workdir, ".chat-bridge.port"), "w").write("%d %d\n" % (a.port, os.getpid()))
    except Exception:
        pass
    print(f"Process Exploration chat bridge → http://127.0.0.1:{a.port}")
    print(f"  answering from {workdir}")
    if _autoexit:
        print("  stops by itself when the page is closed  (--keep-alive to stay up)")
        threading.Thread(target=watchdog, args=(srv,), daemon=True).start()
    print("  Ctrl-C to stop")

    # Ask for the teardown explicitly rather than waiting for KeyboardInterrupt: the main
    # thread sits in selectors.select(), which does not reliably raise it, and a signal
    # that only stops the server would leave the `claude` children running. The handler
    # hands the work to a thread — kill_children() waits, and a signal handler must not.
    def on_signal(signum, frame):
        threading.Thread(target=shutdown, args=(srv, "interrupted"), daemon=True).start()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, on_signal)
        except (ValueError, OSError):
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        shutdown(srv, "interrupted")
    finally:
        kill_children()
    srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
