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
CLIENT_TTL = 50                   # no beat for this long and the page is gone
BYE_GRACE = 8                     # a "bye" may be a reload — wait before acting
WATCH_TICK = 2

_clients = {}                     # session id -> last beat, monotonic seconds
_clients_lock = threading.Lock()
_saw_client = False               # never auto-exit before a page has ever connected
_procs = set()                    # every live `claude` child, so none is orphaned
_procs_lock = threading.Lock()
_shutting_down = threading.Event()
_autoexit = True


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


def drop_partials(workdir):
    """A translation interrupted by shutdown leaves nothing behind."""
    removed = []
    for state in list(_translating.values()):
        state["cancel"] = True
    for path in glob.glob(os.path.join(workdir, "index.*.html.partial")):
        try:
            os.unlink(path); removed.append(os.path.basename(path))
        except Exception:
            pass
    return removed


def shutdown(srv, why):
    """Stop serving, kill the children, keep the exploration."""
    if _shutting_down.is_set():
        return
    _shutting_down.set()
    n = kill_children()
    partials = drop_partials(srv.workdir)
    print("\nbridge stopping — %s" % why, file=sys.stderr)
    if n:
        print("  stopped %d claude subprocess%s" % (n, "" if n == 1 else "es"), file=sys.stderr)
    if partials:
        print("  discarded unfinished %s" % ", ".join(partials), file=sys.stderr)
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
    """Exit once every page that was open has gone."""
    while not _shutting_down.is_set():
        time.sleep(WATCH_TICK)
        now = time.monotonic()
        with _clients_lock:
            for sid, last in list(_clients.items()):
                if now - last > CLIENT_TTL:
                    _clients.pop(sid, None)
            live, saw = len(_clients), _saw_client
        if saw and not live:
            return shutdown(srv, "the page was closed")


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

    # 1. JS data blocks — walked, not regexed.
    #    A quote-pair regex drifts out of alignment the moment one escaped quote appears
    #    earlier in the region, and silently stops capturing prose after it. Walk the text
    #    instead: pair double quotes properly, and skip single-quoted and template spans
    #    wholesale (apostrophes and ${...} live there).
    try:
        a = html.index("const EX="); b = html.index("const REGISTRY=")
        js = html[a:b]
    except ValueError:
        js = ""
    #    Comments must go first: an apostrophe in a comment ("the reader's own record")
    #    would otherwise open a false single-quoted span and swallow every string until
    #    the next apostrophe — which is how whole KPI and problem paragraphs went missing.
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


def translate_batch(exe, workdir, language, topic, lines, offset, state=None):
    numbered = "\n".join("%d. %s" % (offset + k, s) for k, s in enumerate(lines))
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
        raise RuntimeError("batch did not return a JSON object")
    return {int(k): v for k, v in obj.items() if str(k).isdigit()}


COMPLETE = 0.995     # coverage at which a page counts as fully translated
MAX_PASSES = 3       # top-up passes inside one request, so one click can finish a page


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


def render_problems(out, code, table, replaced):
    """Everything that would make a rendered page unfit to keep."""
    problems = []
    node = shutil.which("node")
    if node:
        try:
            js = out[out.rindex("<script>") + 8:out.rindex("</script>")]
            import tempfile
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                             encoding="utf-8") as fh:
                fh.write(js); js_path = fh.name
            chk = subprocess.run([node, "--check", js_path],
                                 capture_output=True, text=True, timeout=60)
            os.unlink(js_path)
            if chk.returncode != 0:
                first = (chk.stderr or "").strip().split("\n")
                detail = next((l for l in first if "Error" in l), first[0] if first else "")
                problems.append("the translated page does not parse: %s" % detail[:200])
        except Exception as e:
            problems.append("could not syntax-check the page: %s" % str(e)[:120])
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
    results = {}
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(translate_batch, exe, workdir, LANGS[code], topic,
                               chunk, start + 1, state): (start, chunk)
                   for start, chunk in slices}
        for fut in cf.as_completed(futures):
            start, chunk = futures[fut]
            try:
                results[start] = fut.result()
                state["done"] = state.get("done", 0) + len(chunk)
            except Cancelled:
                for f in futures:
                    f.cancel()
                return {"error": "cancelled"}
            except Exception as e:
                for f in futures:
                    f.cancel()
                return {"error": "batch-failed",
                        "detail": "strings %d-%d: %s" % (start + 1, start + len(chunk), e)}
    if state["cancel"]:
        return {"error": "cancelled"}
    state["phase"] = "substituting"
    for start, chunk in slices:
        got = results.get(start, {})
        for k, s in enumerate(chunk):
            v = got.get(start + 1 + k)
            if isinstance(v, str) and v.strip() and v.strip() != s:
                table[s] = v
            else:
                missing.append(s)
                if isinstance(v, str) and v.strip() == s:
                    identical.append(s)          # answered, and deliberately unchanged
    if strict and len(table) < len(strings) * 0.75:
        return {"error": "translation-incomplete",
                "detail": "%d of %d strings came back translated; first missed: %s"
                          % (len(table), len(strings), "; ".join(missing[:3]))}
    out, replaced = base, 0
    for s in sorted(table, key=len, reverse=True):
        out, hits = substitute(out, s, table[s])
        if hits:
            replaced += 1
    out = re.sub(r"const CURRENT_LANG='[a-z]{2}'", "const CURRENT_LANG='%s'" % code, out)
    return out, table, missing, replaced, identical


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
        return {"error": "already-running"}

    started = translation_coverage(workdir, code)     # 0.0 when nothing is there yet
    if os.path.isfile(path) and started >= COMPLETE:
        return {"file": target, "cached": True, "coverage": started}

    state = {"cancel": False, "procs": [], "phase": "reading",
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

        kept = load_kept(workdir, code)
        cov, passes, translated, replaced_total, left = started, 0, 0, 0, 0
        while passes < MAX_PASSES:
            strings = allstr if (first and passes == 0) else [s for s in allstr if s in out]
            left = len(strings)
            if not strings:
                break
            state["pass"] = passes + 1
            state["phase"] = "translating"
            res = translate_pass(exe, workdir, code, topic, out, strings, state,
                                 strict=(first and passes == 0))
            if isinstance(res, dict):                 # a pass failed or was cancelled
                if passes == 0:
                    return res                        # nothing earned yet — report it
                break                                 # keep what earlier passes achieved
            cand, table, missing, replaced, identical = res
            state["phase"] = "checking"
            problems = render_problems(cand, code, table, replaced)
            if problems:
                if passes == 0:
                    return {"error": "validation-failed", "detail": "; ".join(problems)}
                break                                 # keep the last good page instead
            passes += 1
            out = cand
            translated += len(table); replaced_total += replaced
            kept |= set(identical)
            cov = coverage_between(english, out, kept)
            state["coverage"] = cov
            if cov >= COMPLETE or not table:
                break
        if state["cancel"]:
            return {"error": "cancelled"}

        state["phase"] = "saving"
        if kept:
            save_kept(workdir, code, kept)
        if cov >= MIN_COVERAGE:
            open(path, "w", encoding="utf-8").write(out)
            if os.path.isfile(partial):
                os.remove(partial)
            register_language(workdir, code, LANGS_LABEL.get(code, LANGS[code]), target)
            return {"file": target, "cached": False, "coverage": cov, "started": started,
                    "passes": passes, "strings": len(allstr), "translated": translated,
                    "substituted": replaced_total, "remaining": left, "kept": len(kept)}
        # Short of usable, but the work is not thrown away: the next attempt continues
        # from here instead of starting the whole page again.
        open(partial, "w", encoding="utf-8").write(out)
        if os.path.isfile(path):
            os.remove(path)
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
        futures = {pool.submit(translate_batch, exe, workdir, LANGS[code], topic,
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

Answer in under 160 words as a practitioner explaining to someone who has never run
this process. **Write the four fields in {language}** — that is the language the reader
has this page open in, and the answer is filed into their notes as it stands. Keep
company, product and place names, codes and terms of art in their usual form.

Return ONLY one JSON object, no prose and no code fence:
{{"topic":"short noun phrase","what":"…","why":"…","example":"…"}}"""


def claude_path():
    return shutil.which("claude")


def claude_version(exe):
    try:
        return subprocess.run([exe, "--version"], capture_output=True, text=True,
                              timeout=20).stdout.strip()
    except Exception:
        return ""


def extract_json(text):
    """The CLI may wrap the object in prose or a fence; take the first {...} block."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
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
                try:
                    return json.loads(text[start:i + 1])
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
    return {k: str(obj.get(k, "")).strip() for k in ("topic", "what", "why", "example")}


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


def translation_coverage(workdir, code):
    """How much of the page a rendered language actually translated, 0.0–1.0.

    Compares the strings extracted from the English page against the translated file:
    anything still appearing verbatim was not translated. Terms of art and names are
    meant to stay identical, so they are excluded from the denominator — otherwise a
    perfect translation would score badly."""
    src = os.path.join(workdir, "index.html")
    tgt = os.path.join(workdir, "index.html" if code == "en" else "index.%s.html" % code)
    if code == "en":
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
        # The generated page is opened from file://, whose Origin is "null".
        # Never grant browser access to arbitrary web origins: while the bridge is
        # alive they could otherwise drive the local Claude CLI and read replies.
        if self.headers.get("Origin") == "null":
            self.send_header("Access-Control-Allow-Origin", "null")
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _trusted_request(self):
        origin = self.headers.get("Origin")
        host = (self.headers.get("Host") or "").split(":", 1)[0].lower()
        return origin in (None, "null") and host in ("127.0.0.1", "localhost")

    def do_OPTIONS(self):
        if not self._trusted_request():
            return self._send(403, {"error": "forbidden-origin"})
        self._send(204, {})

    def do_GET(self):
        if not self._trusted_request():
            return self._send(403, {"error": "forbidden-origin"})
        route = urlparse(self.path).path.rstrip("/") or "/"
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
                                    "cancelling": bool(st.get("cancel"))})
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
        if not self._trusted_request():
            return self._send(403, {"error": "forbidden-origin"})
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
        try:
            self._send(200, ask_claude(exe, self.server.workdir, payload))
        except subprocess.TimeoutExpired:
            self._send(504, {"error": "timeout"})
        except Exception as e:
            self._send(500, {"error": "bridge-failed", "detail": str(e)[:400]})


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
                    os._exit(0)
                continue
            gone = 0
            if time.time() - LAST_SEEN[0] > IDLE_EXIT and not _translating:
                print("! idle for %dh - retiring this bridge" % (IDLE_EXIT // 3600),
                      file=sys.stderr, flush=True)
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
