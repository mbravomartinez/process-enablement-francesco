#!/usr/bin/env python3
"""Give stored pages the structured-example block that every Process Challenge and KPI now
carries (see skills/explore/references/html-spec.md).

Three edits per page, all idempotent, none of them content:

  1. the `.exlines` CSS, before the `.facts` rule;
  2. the shared `exampleHTML()` helper, before `const PROBS=[`;
  3. the two render calls — a `stage` in `drawProbs`, a `lbl` in `drawKpis` — each guarded on
     the field being present, so a page whose data has no examples yet still draws exactly as
     it did.

The examples themselves are content and belong to the page: this script only makes a page
able to render them. Anchors are JS, never prose, so a translated page patches the same way
as an English one — its new headings arrive in English and are picked up by the next
re-translate pass, like every other chrome label.

    pe-add-examples.py [--library DIR] [--check] [FILES...]
"""
import argparse, glob, os, re, shutil, sys, time

CSS = """/* ---- a structured example: labelled lines, values aligned ----
   Every challenge and every KPI carries one, and it is never a paragraph: a reader checking
   whether they have understood the mechanism wants the case laid out, not narrated. Grid so
   the values line up under each other; the last line is always the effect. */
.exlines{display:grid;grid-template-columns:max-content 1fr;gap:4px 12px;margin:0;
 padding:11px 13px;background:#fafafb;border:1px solid var(--line);
 border-left:2px solid var(--accent);border-radius:0 4px 4px 0;max-width:46em}
.exlines b{font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
 font-weight:600;padding-top:2px;white-space:nowrap}
.exlines span{font-size:13px;color:var(--ink2)}
@media(max-width:940px){.exlines{grid-template-columns:1fr;gap:1px 0}.exlines b{padding-top:7px}}
"""

HELPER = """/* One example renderer for both Process Challenges and KPIs. The field is written as
   "Label: value" lines separated by newlines; a line without a colon renders as a value with
   no label, which is how a closing sentence gets in. Absent field renders nothing, so a page
   generated before this rule still draws. */
function exampleHTML(ex){
  if(!ex) return '';
  const rows=String(ex).split('\\n').map(l=>l.trim()).filter(Boolean).map(l=>{
    const i=l.indexOf(':');
    return i>0 ? `<b>${l.slice(0,i)}</b><span>${l.slice(i+1).trim()}</span>`
               : `<b></b><span>${l}</span>`;
  }).join('');
  return `<div class="exlines">${rows}</div>`;
}
"""

PROB_CALL = ("\n    ${p.example?`<div class=\"stage\"><h5>Example — the running case</h5>"
             "${exampleHTML(p.example)}</div>`:''}")
KPI_CALL = ("\n    ${k.example?`<div class=\"lbl\">Example — the running case</div>"
            "${exampleHTML(k.example)}`:''}")


def patch(text):
    """-> (new_text, [what changed]); already-patched input returns no changes."""
    done = []
    if ".exlines{" not in text:
        m = re.search(r"^\.facts\{margin-top", text, re.M)
        if not m:
            return None, ["no .facts rule to anchor the CSS to"]
        text = text[:m.start()] + CSS + text[m.start():]
        done.append("css")
    if "function exampleHTML" not in text:
        m = re.search(r"^const PROBS=\[", text, re.M)
        if not m:
            return None, ["no PROBS array to anchor the helper to"]
        text = text[:m.start()] + HELPER + text[m.start():]
        done.append("helper")
    if "exampleHTML(p.example)" not in text:
        anchor = "${p.challenge}</p></div>"
        if anchor not in text:
            return None, ["no drawProbs render to patch"]
        text = text.replace(anchor, anchor + PROB_CALL, 1)
        done.append("drawProbs")
    if "exampleHTML(k.example)" not in text:
        m = re.search(r"\$\{k\.trap\}</p>(?=\s*\n\s*\$\{k\.svg)", text)
        if not m:
            return None, ["no drawKpis render to patch"]
        text = text[:m.end()] + KPI_CALL + text[m.end():]
        done.append("drawKpis")
    return text, done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", default=os.path.expanduser(
        os.environ.get("PE_HOME", "~/.process-enablement") + "/output"))
    ap.add_argument("--check", action="store_true", help="report, write nothing")
    ap.add_argument("files", nargs="*")
    a = ap.parse_args()

    files = a.files or sorted(glob.glob(os.path.join(a.library, "*", "index*.html")))
    if not files:
        print("no pages found under " + a.library)
        return 1
    backup = os.path.join(os.path.dirname(a.library.rstrip("/")),
                          "backup-examples-" + time.strftime("%Y%m%d-%H%M%S"))
    changed = failed = 0
    for f in files:
        text = open(f, encoding="utf-8").read()
        new, done = patch(text)
        label = os.path.join(os.path.basename(os.path.dirname(f)), os.path.basename(f))
        if new is None:
            print("SKIP\t%s\t%s" % (label, "; ".join(done)))
            failed += 1
            continue
        if not done:
            print("in-sync\t%s" % label)
            continue
        changed += 1
        if a.check:
            print("would patch\t%s\t%s" % (label, ", ".join(done)))
            continue
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
