#!/usr/bin/env python3
"""pe-sync-template.py — push the template's shared chrome into every stored exploration.

THE RULE THIS TOOL EXISTS TO ENFORCE
    A change to the plugin's page chrome is not finished until every page in the library
    has it. A library where four explorations behave four different ways is not a
    library, it is four one-off files, and a reader who clicks the same control on two
    pages must get the same behaviour.

WHY THIS IS NOT "RE-RENDER THE PAGE FROM THE TEMPLATE"
    It would be tidier if a stored page were the template plus a few data blocks, and
    could simply be regenerated. It is not. Measured across this library, a page is
    ~99% template *by line count* but each one also carries 80-100 lines of its own
    markup and 200-265 lines of its own code and CSS: the prose of its Overview, its
    document-card renderers, consts the template has never heard of. That content came
    from research and a customer's own material, and no template can reproduce it — a
    re-render would silently replace an exploration with a generic one.

    So the page is treated as two layers, and only one of them is owned here:
      * the CHROME  — the chat, the bridge probe, the refresh control, the status dot,
                      the shared CSS for those. Identical on every page by definition,
                      owned by the template, and what this tool replaces.
      * the EXPLORATION — everything else: data blocks, prose, per-page renderers.
                      Never touched.

    The regions below are the chrome, located by anchors that exist in every page rather
    than by fences that would have to be migrated into pages already on disk. A page
    missing an anchor is reported and skipped whole — never half-synced.

    pe-sync-template.py                 sync every page in the library
    pe-sync-template.py --check         report drift, write nothing
    pe-sync-template.py --base-only     skip index.<lang>.html (see the note on those)
    pe-sync-template.py FILE...         just these pages

TRANSLATED PAGES
    index.<lang>.html carries the chrome with its user-visible strings translated. The
    template's chrome is English, so syncing one returns those few labels to English
    until the next translate pass regenerates them. That is the right trade: stale
    *code* on a translated page is a broken control, while an English status label is a
    cosmetic regression with a known fix. Every such page is named in the report.
"""
import argparse, difflib, glob, os, re, subprocess, sys, tempfile, time

# (name, first line contains, last line contains, end_inclusive)
REGIONS = [
    ("chat-chrome-css", ".dot2{width:7px", "@media print{button.hlBtn,.selbar{display:none}", True),
    # The note CSS, for the same reason the notes engine is here: the refine control was added
    # to a note card and styled in this block, which no region covered — so the JS synced, the
    # styling did not, and every page but the template rendered the control as unstyled empty
    # boxes. Widen the region; never hand-edit the pages.
    ("notes-css",       ".noteEmpty{border:1px dashed", "/* ============ quiz overlay ============ */", False),
    # The notes engine belongs here too. It looked like it could stay out of the sync until
    # `addNote` had to learn about anchors: a stored page kept its own two-argument version,
    # so the selection engine handed it an anchor it silently dropped and no highlight could
    # ever appear. Verified across the library as pure chrome — not one page declares
    # anything of its own inside this span.
    ("notes-engine",    "const NOTE_KEY='pe-notes-'", "let BRIDGE=null,",                    False),
    ("chat-engine",     "let BRIDGE=null,", "/* ---------- PE:chrome-split ---------- */", False),
    ("selection-engine", "/* ---------- PE:chrome-split ---------- */",
                         "/* ---------- PE:tour ---------- */",                           False),
    # The guided tour. Chrome by every measure — the same twelve steps on every page, none of
    # them derived from the exploration — so it syncs like the rest of it. Split from the
    # selection engine at its own sentinel, the same arrangement as chrome-split below.
    ("tour",            "/* ---------- PE:tour ---------- */",
                        "/* ---------- quiz: 10 questions",                               False),
]

# The two JS regions are adjacent, split at a sentinel comment the template carries. A page
# that has never been synced has neither the sentinel nor the selection engine, so
# `chat-engine` falls back to the end anchor every page does have (the quiz comment) and the
# whole span — sentinel, selection engine and all — arrives in one replacement. From the
# second sync onward both regions resolve normally and report drift separately.
# Same story for the CSS region: its new end anchor is the print rule that came with the
# selection engine, which a page acquires only by being synced. Until then, end where every
# page still ends.
FALLBACK_END = {"chat-engine": "/* ---------- quiz: 10 questions",
                "selection-engine": "/* ---------- quiz: 10 questions",
                "tour": "/* ---------- quiz: 10 questions",
                "chat-chrome-css": ".msg.ai{background:#f4f4f6;color:var(--ink2)}"}
FALLBACK_INCLUSIVE = {"chat-chrome-css": True}
# When a region's fallback span is used, the TEMPLATE side must cover the same ground or the
# replacement drops whatever sits between the two anchors. For chat-engine that gap is the
# entire selection engine, so the template span is widened to the same fallback end and both
# JS regions arrive as one block. (chat-chrome-css needs no widening: its new content sits
# after its fallback end, so the template's own span already includes it.)
# selection-engine joins them for the same reason chat-engine did: a page that predates the
# tour has no PE:tour sentinel, so the selection engine falls back to the quiz anchor and the
# tour arrives inside that one replacement. From the next run both resolve and report
# separately. (`tour` needs the fallback only so a page missing the sentinel does not report a
# phantom region; its content came with the widened selection-engine span.)
FALLBACK_WIDENS_TEMPLATE = {"chat-engine", "selection-engine"}

# Identifier drift to repair while we are here. An early translate pass renamed JS
# identifiers along with the prose, so a page can carry `bridgeStato` where the template
# says `bridgeState`. Syncing the chrome alone would leave the *rest* of that page
# calling a name that no longer exists, so the rename is undone page-wide.
REPAIRS = {"bridgeStato": "bridgeState", "setChatStato": "setChatStatus"}


def region(lines, first, last, end_inclusive):
    """The half-open line span of one region, or None if either anchor is missing."""
    a = next((i for i, l in enumerate(lines) if first in l), None)
    if a is None:
        return None
    b = next((i for i in range(a + 1, len(lines)) if last in lines[i]), None)
    if b is None:
        return None
    return (a, b + 1 if end_inclusive else b)


def node_available():
    return any(os.access(os.path.join(d, "node"), os.X_OK)
               for d in os.environ.get("PATH", "").split(os.pathsep) if d)


def node_check(text):
    """Every <script> body must parse, exactly as pe-splice.py insists. A page that
    cannot parse is worse than a page with stale chrome, so this gates the write."""
    if not node_available():
        return None
    for i, body in enumerate(re.findall(r"<script\b[^>]*>(.*?)</script>", text, re.S)):
        if not body.strip():
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(body)
            tmp = f.name
        try:
            r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
            if r.returncode:
                first = (r.stderr or "").strip().splitlines()
                return "script #%d: %s" % (i + 1, first[0] if first else "parse error")
        finally:
            os.unlink(tmp)
    return None


def sync_one(tmpl_lines, path):
    """-> (new_text or None, note, changed_regions)."""
    src = open(path, encoding="utf-8").read()
    lines = src.splitlines(keepends=True)
    changed = []
    for name, first, last, inc in REGIONS:
        t = region(tmpl_lines, first, last, inc)
        p = region(lines, first, last, inc)
        if t is None:
            return None, "SKIP template has no %s region" % name, []
        if p is None and name in FALLBACK_END:
            p = region(lines, first, FALLBACK_END[name],
                       FALLBACK_INCLUSIVE.get(name, False))       # not yet synced
            if p is not None and name in FALLBACK_WIDENS_TEMPLATE:
                t = region(tmpl_lines, first, FALLBACK_END[name], False) or t
        if p is None:
            if name == "selection-engine":
                continue        # already carried in by chat-engine's fallback span
            return None, "SKIP no %s region (anchors missing)" % name, []
        new = tmpl_lines[t[0]:t[1]]
        if lines[p[0]:p[1]] != new:
            changed.append("%s (%d->%d lines)" % (name, p[1] - p[0], len(new)))
        lines[p[0]:p[1]] = new
    out = "".join(lines)
    for bad, good in REPAIRS.items():
        if re.search(r"\b%s\b" % bad, out):
            out = re.sub(r"\b%s\b" % bad, good, out)
            changed.append("repaired %s->%s" % (bad, good))
    if out == src:
        return None, "in-sync", []
    err = node_check(out)
    if err:
        return None, "SKIP would not parse: %s" % err, changed
    return out, "sync", changed


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.realpath(__file__))
    ap.add_argument("files", nargs="*")
    ap.add_argument("--template", default=os.path.join(
        here, "..", "skills", "explore", "assets", "reference-mock.html"))
    ap.add_argument("--library", default=os.path.join(
        os.environ.get("PE_HOME") or os.path.expanduser("~/.process-enablement"), "output"))
    ap.add_argument("--check", action="store_true", help="report drift, write nothing")
    ap.add_argument("--base-only", action="store_true", help="skip index.<lang>.html")
    ap.add_argument("--no-backup", action="store_true")
    a = ap.parse_args()

    tmpl = os.path.realpath(a.template)
    if not os.path.isfile(tmpl):
        print("no template at %s" % tmpl, file=sys.stderr)
        return 2
    tmpl_lines = open(tmpl, encoding="utf-8").read().splitlines(keepends=True)

    files = a.files or sorted(glob.glob(os.path.join(a.library, "*", "index*.html")))
    if a.base_only:
        files = [f for f in files if os.path.basename(f) == "index.html"]
    if not files:
        print("no pages found under %s" % a.library)
        return 0
    if not node_available():
        print("note\tno node on PATH — writing without the JS parse gate")

    backup = None
    if not a.check and not a.no_backup:
        backup = os.path.join(os.path.dirname(a.library.rstrip("/")),
                              "backup-sync-%s" % time.strftime("%Y%m%d-%H%M%S"))

    synced, skipped, translated = 0, 0, []
    for f in files:
        out, note, changed = sync_one(tmpl_lines, f)
        label = os.path.join(os.path.basename(os.path.dirname(f)), os.path.basename(f))
        if note.startswith("SKIP"):
            print("SKIP\t%s\t%s" % (label, note[5:])); skipped += 1; continue
        if note == "in-sync":
            print("in-sync\t%s" % label); continue
        if a.check:
            print("drift\t%s\t%s" % (label, "; ".join(changed))); synced += 1; continue
        if backup:
            dst = os.path.join(backup, label)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "w", encoding="utf-8").write(open(f, encoding="utf-8").read())
        open(f, "w", encoding="utf-8").write(out)
        print("synced\t%s\t%s" % (label, "; ".join(changed))); synced += 1
        if re.match(r"index\.[a-z]{2}\.html$", os.path.basename(f)):
            translated.append(label)

    print()
    print("%d %s, %d skipped, from %s"
          % (synced, "would sync" if a.check else "synced", skipped,
             os.path.relpath(tmpl, os.path.dirname(here))))
    if backup and synced:
        print("previous versions: %s" % backup)
    if translated:
        print("re-translate these — their chrome labels are English again until you do:")
        for t in translated:
            print("  %s" % t)
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
