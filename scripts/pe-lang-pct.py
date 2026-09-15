#!/usr/bin/env python3
"""Make a running translation report a percentage, and say how long a whole page takes.

The language row used to read `translating… 1:12` for the first minutes of a run — the whole
time before the first batch came back — and again whenever the bridge reported nothing to
count. A number is what the reader wants: where the page is now, from the coverage it started
at. So the row leads with the percentage always, and the fallback is the coverage the run
resumed from (52% for a page half done) rather than a word.

The language block sits after the quiz, outside every region `pe-sync-template.py` owns, so
stored pages cannot receive this by syncing — hence a migration, idempotent like its siblings:

  1. `jobPct()` no longer returns null when nothing has landed yet — it reports the coverage
     the run started from, so a resumed page opens at 52% instead of a word;
  2. `jobLabel()` leads with that percentage and drops both "translating…" and "finishing…";
  3. the menu hint states the expectation — a whole page takes 5–10 minutes — because a reader
     watching a number move in whole-batch steps has no other way to know whether it is working.

Each step is guarded on its own, so the script can be re-run to pick up a step added later.

Anchors are JS, never prose, so a translated page patches like an English one.

    pe-lang-pct.py [--library DIR] [--check] [FILES...]
"""
import argparse, glob, os, re, shutil, sys, time

PCT_OLD_RE = re.compile(
    r"""  /\* Batches land whole.*?\n  const share=\(p\.total&&p\.done\)\?p\.done/p\.total:0;\n"""
    r"""  if\(!share&&!base\) return null;\n""", re.S)
PCT_NEW = """  /* Batches land whole, so there is nothing new to show until the first one is back —
     until then the row shows where this run started (52% for a resumed page, 0% for a new
     one). A number that has not moved yet still says more than a word does. */
  const share=(p.total&&p.done)?p.done/p.total:0;
"""

LABEL_OLD_RE = re.compile(
    r"""function jobLabel\(job\)\{\n"""
    r"""  if\(job\.cancelled\) return 'stopping…';\n"""
    r"""  const t=mmss\(Date\.now\(\)-job\.t0\), p=job\.prog, pct=jobPct\(job\);\n"""
    r"""  if\(p&&p\.running&&\(p\.phase==='checking'\|\|p\.phase==='saving'\)\) return 'finishing… '\+t;\n"""
    r"""  return \(pct===null\?'translating… ':pct\+'% · '\)\+t;\n\}""")
LABEL_NEW = """function jobLabel(job){
  if(job.cancelled) return 'stopping…';
  /* The percentage leads, always: "translating…" told the reader only that they were waiting,
     and it sat there for the minutes before the first batch landed. */
  const t=mmss(Date.now()-job.t0), pct=jobPct(job);
  return (pct===null?0:pct)+'% · '+t;
}"""

MARK = "The percentage leads, always"

# The hint is the only place a reader is told what to expect, and the sentence is prose — so on
# a translated page it is whatever that language says. Anchor on the two <b> tags around it,
# which are chrome the translator leaves alone, and insert between them.
HINT_ANCHOR = "A language reads <b>ready</b> only when the whole page is translated."
HINT_ADD = ("A whole page takes <b>5\u201310 minutes</b>, so leave it running; the percentage in "
            "the row is how far it has got. ")
HINT_MARK = "5\u201310 minutes"


def patch(text):
    if "function jobLabel(job){" not in text:
        return None, ["no language-menu progress label (older generation)"]
    done = []
    if MARK not in text:
        text, n = LABEL_OLD_RE.subn(LABEL_NEW, text, count=1)
        if not n:
            return None, ["jobLabel() is not the expected shape"]
        done.append("percentage label")
    if "if(!share&&!base) return null;" in text:
        text, n = PCT_OLD_RE.subn(PCT_NEW, text, count=1)
        if not n:
            return None, ["jobPct() present but not matchable"]
        done.append("no null fallback")
    if HINT_MARK not in text:
        if HINT_ANCHOR not in text:
            return None, ["no language-menu hint to extend"]
        text = text.replace(HINT_ANCHOR, HINT_ADD + HINT_ANCHOR, 1)
        done.append("how long it takes")
    return text, done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", default=os.path.expanduser(
        os.environ.get("PE_HOME", "~/.process-enablement") + "/output"))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("files", nargs="*")
    a = ap.parse_args()

    files = a.files or sorted(glob.glob(os.path.join(a.library, "*", "index*.html")))
    if not files:
        print("no pages found under " + a.library)
        return 1
    backup = os.path.join(os.path.dirname(a.library.rstrip("/")),
                          "backup-langpct-" + time.strftime("%Y%m%d-%H%M%S"))
    changed = failed = 0
    for f in files:
        text = open(f, encoding="utf-8").read()
        new, done = patch(text)
        label = os.path.join(os.path.basename(os.path.dirname(f)), os.path.basename(f))
        if new is None:
            print("SKIP\t%s\t%s" % (label, "; ".join(done))); failed += 1; continue
        if not done:
            print("in-sync\t%s" % label); continue
        changed += 1
        if a.check:
            print("would patch\t%s\t%s" % (label, ", ".join(done))); continue
        d = os.path.join(backup, os.path.basename(os.path.dirname(f)))
        os.makedirs(d, exist_ok=True)
        shutil.copy2(f, os.path.join(d, os.path.basename(f)))
        open(f, "w", encoding="utf-8").write(new)
        print("patched\t%s\t%s" % (label, ", ".join(done)))
    print("\n%d %s, %d skipped" % (changed, "would patch" if a.check else "patched", failed))
    if changed and not a.check:
        print("previous versions: " + backup)
    return 0


if __name__ == "__main__":
    sys.exit(main())
