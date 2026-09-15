#!/usr/bin/env python3
"""Put the Claude refresh control on the language menu's header row, in pages that predate it.

Translation needs a Claude session, and the language menu is where a reader finds that out —
*needs Claude* against every language they cannot have. The control that starts one therefore
belongs in that menu, on the same line as the LANGUAGE label, and the menu's own hint should
name it rather than only offering a shell command.

The language block sits outside every region `pe-sync-template.py` owns (it follows the quiz),
so this is the one part of the feature a stored page cannot receive by syncing. Five steps, each
skipped when already done, so the script is safe to re-run and safe on a page that got an
earlier version of it:

  1. the `LANG_RFSH` button markup, declared before `drawLangMenu()`;
  2. CSS for the header row — `.langmenu button` sets `width:100%`, which is what dropped the
     icon onto a line of its own, centred, under the label;
  3. label and button wrapped in that row;
  4. a branch in the menu's click handler calling `refreshBridge()` — the same function the
     chat's control calls, which spins both buttons — then redrawing, so a language that read
     *needs Claude* a moment ago reads *translate*;
  5. the no-session hint reworded to point at the button;
  6. the can-generate hint extended to say what a percentage means — a reader seeing
     *80% — finish* in the list cannot otherwise know it offers to translate only the strings
     that came back in English, rather than the page again;
  7. `jobPct()` replaced so a running translation reports **page coverage**, climbing from the
     80 per cent it started at, instead of batches done in the current pass — which restarted
     at zero and made a top-up look like it had begun the whole page again;
  8. the menu made sticky — a click inside it (translate, stop, refresh, or dead space) no
     longer closes it, since that hid the progress the reader had just started; only an outside
     click closes it, or picking a language that already exists and navigates away;
  9. `adoptJobs()` plus a poller that can end a job it did not start — a page reloaded during a
     translation showed "translate" for the language being translated; now it asks the bridge's
     /jobs what is running for this exploration and shows it, with the clock the run really has;
 10. CSS keeping `b` inline inside that hint — `.langmenu b` is the menu's section label
     (block, uppercase, indented), which broke the hint sentence into three fragments wherever
     it quoted a word from the list, such as *translate* or *ready*.

Anchors are JS and CSS, never prose, so a translated page patches like an English one — with one
exception that cannot be helped: step 5 replaces whatever that hint currently says, in whatever
language, with the new English sentence. Those pages are queued for a re-translate pass anyway.
(`'<b>Language</b>'` is safe as an anchor: *Language* is in the translator's KEEP_ALWAYS list, so
the menu header stays English in every language.)

    pe-add-lang-refresh.py [--library DIR] [--check] [FILES...]
"""
import argparse, glob, os, re, shutil, sys, time

CONST = '''/* Translation needs a Claude session, and this menu is where a reader learns that — "needs
   Claude" against every language they cannot have. So the same refresh the chat offers lives
   here too, rather than sending them to the other side of the page to press it. */
const LANG_RFSH='<button type="button" class="rfsh" id="langRfsh" data-langrfsh'
  +' title="Check for a Claude session — start one if none is running, so a language can be generated"'
  +' aria-label="Check for a Claude session"><svg viewBox="0 0 16 16" width="11" height="11" aria-hidden="true" focusable="false">'
  +'<path d="M13.6 8a5.6 5.6 0 1 1-1.64-3.96" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>'
  +'<path d="M13.9 1.9v3.2h-3.2" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></button>';
'''

HINT_CSS = """/* `.langmenu b` is the menu's section label — block, uppercase, padded. Inside the hint, `b`
   is quoting a word the reader can see in the list above ("marked translate", "offered as
   ready"), so it has to stay inline: as a block it broke the sentence into three, each with
   the label's own indent and capitals. */
.langmenu .hint b{display:inline;padding:0;font-size:inherit;text-transform:none;
 letter-spacing:0;font-weight:600;color:var(--ink2)}
.langmenu .hint code{background:var(--line2);border-radius:3px;padding:0 4px;font-size:10.5px}
"""

CSS = """.langmenu .lang-hd{display:flex;align-items:center;gap:6px;padding:0 7px 0 0}
.langmenu .lang-hd b{flex:1}
.langmenu .lang-hd .rfsh{display:inline-flex;width:18px;height:18px;min-width:0;flex:none;
 padding:0;margin:0;border:1px solid var(--line);border-radius:4px;background:#fff;color:var(--muted)}
.langmenu .lang-hd .rfsh:hover{background:var(--line2);color:var(--ink2);border-color:var(--ink2)}
"""

HEAD_NEW = ('  langMenu.innerHTML = \'<div class="lang-hd"><b>Language</b>\' + LANG_RFSH'
            " + '</div>' + LANGS.map(l=>{")

CLICK_OLD = ("langMenu.addEventListener('click',e=>{\n"
             "  const s=e.target.closest('[data-stop]');")
CLICK_NEW = ("langMenu.addEventListener('click',async e=>{\n"
             "  const r=e.target.closest('[data-langrfsh]');\n"
             "  if(r){ e.stopPropagation(); await refreshBridge(); return void drawLangMenu(); }\n"
             "  const s=e.target.closest('[data-stop]');")

# A click inside the menu must not close it. Starting a translation, stopping one, pressing the
# refresh or missing a row are all done while watching the list, and closing it under the reader
# hides the progress they just asked for. Only an outside click closes it — plus picking a
# language that already exists, which navigates away.
STICKY_OLD = "langMenu.addEventListener('click',async e=>{\n"
STICKY_NEW = ("/* A click INSIDE this menu never closes it: only a click outside does, or picking a\n"
              "   language that already exists, which navigates away anyway. */\n"
              "langMenu.addEventListener('click',async e=>{\n"
              "  e.stopPropagation();\n")
HIDE_OLD = "  const code=b.dataset.lang;\n  langMenu.hidden=true;\n"
HIDE_NEW = "  const code=b.dataset.lang;\n"
NAV_OLD = "  if(langAvailable(code)){\n"
NAV_NEW = ("  if(langAvailable(code)){\n"
           "    langMenu.hidden=true;                       /* leaving the page — the menu goes with it */\n")

# The hint is a ternary chain whose branch count has changed between generations — an older
# page has two branches, a newer one three. Match its LAST branch instead of a fixed shape:
# only the final `: '...'` is followed by the closing `) + '</div>'`.
# The other hint — the one shown when a language CAN be generated. Same structural match: its
# first branch, whatever language it currently speaks. A reader seeing "80% — finish" in the list
# has no way to know what it offers unless this sentence says so.
READY_HINT_RE = re.compile(r"(\+ \(canGenerate\s*\n\s*\?\s*)'(?:[^'\\]|\\.)*'")
READY_HINT_NEW = (
    "'Pick a language marked <b>translate</b> and it is generated once, then saved beside this "
    "file \u2014 after that it opens instantly. A language reads <b>ready</b> only when the whole "
    "page is translated. A percentage instead, such as <b>80% \u2014 finish</b>, means that "
    "language already exists but part of it came back in English: <b>finish</b> translates just "
    "those missing strings, never the page again.'")

# The progress percentage a running translation reports. The original counted batches inside
# the current pass, which starts at zero however much of the page is already done, so a
# top-up from "80 per cent - finish" appeared to throw that progress away and start over. It
# never did: the bridge sends only the strings still verbatim English (see translate() in
# chat-bridge.py) and applies them on top. This reports the page instead, climbing from
# where the run started.
JOBPCT_RE = re.compile(r"function jobPct\(job\)\{[\s\S]*?\n\}")
JOBPCT_NEW = 'function jobPct(job){\n  const p=job.prog;\n  if(!p||!p.running) return null;\n  /* Two different percentages used to collide here. The row that offered "80% — finish" was\n     talking about the page: 80% of it is translated. This was reporting batches finished in\n     the current pass, which starts at zero however much of the page is already done — so a\n     top-up looked like it had thrown the 80% away and begun again. It had not: the bridge\n     sends only the strings still verbatim English and applies them on top.\n\n     So report the page instead — where this run started, plus the share of what was left\n     that has come back — and never let it fall: a pass that achieves less than the\n     straight-line estimate would otherwise tick backwards. */\n  const base=typeof p.coverage===\'number\'?Math.max(0,Math.min(1,p.coverage)):0;\n  /* Batches land whole, so there is nothing new to show until the first one is back. With\n     nothing translated yet either, the row says "translating…" rather than a stuck 0%. */\n  const share=(p.total&&p.done)?p.done/p.total:0;\n  if(!share&&!base) return null;\n  /* held below 100 while anything is still being written: the row is not done until the\n     bridge has answered. */\n  const pct=Math.min(99,Math.floor((base+(1-base)*share)*100));\n  job.shown=Math.max(job.shown||0,pct);\n  return job.shown;\n}'

# Translations run in the bridge, not in the page. Reload mid-run and JOBS is empty, so the
# menu offered "translate" for the language being translated right then. adoptJobs() asks
# /jobs what is running for this exploration and takes it over, clock and all; the poller
# gains the ability to end a job it did not start.
ADOPT = '/* Translations run in the bridge, not in the page: reload mid-run and JOBS is empty, so the\n   menu would offer "translate" for the language being translated right now. Ask what is running\n   for this exploration and adopt it — the row then shows its percentage and its stop, with a\n   clock that starts where the run actually started rather than at zero. */\nlet adopting=false;\nasync function adoptJobs(){\n  if(adopting || !BRIDGE) return;\n  adopting=true;\n  try{\n    const r=await fetch(BRIDGE+\'/jobs?exploration=\'+encodeURIComponent(here().path),{cache:\'no-store\'});\n    const a=await r.json();\n    const running=(a&&a.running)||{};\n    let added=0;\n    for(const code of Object.keys(running)){\n      if(JOBS[code]) continue;                    /* already ours — leave its own clock alone */\n      const p=running[code], l=LANGS.find(x=>x.code===code);\n      JOBS[code]={t0:Date.now()-Math.round((p.elapsed||0)*1000),\n                  label:l?l.label:code, cancelled:!!p.cancelling, prog:p, adopted:true};\n      added++;\n    }\n    if(added){ if(!langMenu.hidden) drawLangMenu(); pollProgress(); }\n  }catch(e){/* no bridge, or an older one without /jobs — nothing to adopt */}\n  finally{ adopting=false; }\n}\n'

POLL_NEW = "        const p=await r.json();\n        const job=JOBS[code]; if(!job) continue;\n        job.prog=p;\n        /* A job this page adopted has no fetch of its own waiting on the answer, so the poller\n           is what ends it: when the bridge stops reporting it, take the row down and ask health\n           for the language's new state. A job started here is left alone — its own fetch\n           resolves with the coverage and the message. */\n        if(job.adopted && p && p.running===false){\n          delete JOBS[code];\n          if(typeof checkBridge==='function') await checkBridge();\n          drawLangMenu();\n        }\n      }catch(e){/* a missed poll just leaves the last figure standing */}"

POLL_OLD = ("        const p=await r.json();\n"
            "        if(JOBS[code]) JOBS[code].prog=p;\n"
            "      }catch(e){/* a missed poll just leaves the last figure standing */}")

HINT_RE = re.compile(r"(\?\s*'<div class=\"sep\"></div><div class=\"hint\">'\s*\+\s*\(canGenerate"
                     r"[\s\S]*?:\s*)'(?:[^'\\]|\\.)*'(\) \+ '</div>')")
HINT_NEW = ("'No Claude session yet. Start one with the refresh button above, "
            "or run <code>pe-chat .</code> yourself.'")


def patch(text):
    """-> (new_text or None, [what changed] or [why not])"""
    done = []

    if "const LANG_RFSH=" not in text:
        if "function drawLangMenu(){" not in text:
            return None, ["no drawLangMenu() to anchor the button markup to"]
        text = text.replace("function drawLangMenu(){", CONST + "function drawLangMenu(){", 1)
        done.append("button markup")

    if ".langmenu .lang-hd{" not in text:
        m = re.search(r"^\.langmenu \.sep\{", text, re.M)
        if not m:
            return None, ["no .langmenu .sep rule to anchor the row CSS to"]
        text = text[:m.start()] + CSS + text[m.start():]
        done.append("row css")

    if ".langmenu .hint b{" not in text:
        m = re.search(r"^\.langmenu \.hint\{[^\n]*\n", text, re.M)
        if not m:
            return None, ["no .langmenu .hint rule to anchor the inline-bold fix to"]
        text = text[:m.end()] + HINT_CSS + text[m.end():]
        done.append("hint css")

    if 'class="lang-hd"' not in text:
        for old in ("  langMenu.innerHTML = '<b>Language</b>' + LANG_RFSH + LANGS.map(l=>{",
                    "  langMenu.innerHTML = '<b>Language</b>' + LANGS.map(l=>{"):
            if old in text:
                text = text.replace(old, HEAD_NEW, 1)
                done.append("header row")
                break
        else:
            return None, ["no language-menu header to wrap"]

    if "data-langrfsh]" not in text:
        if CLICK_OLD not in text:
            return None, ["no language-menu click handler to patch"]
        text = text.replace(CLICK_OLD, CLICK_NEW, 1)
        done.append("click handler")

    # An older generation has no progress poller at all — its rows only ever said
    # "translating… mm:ss" — and there is nothing to hang adoption on without backporting the
    # whole language block. Left alone; re-translating that page from the current template is
    # what brings it forward.
    if "function pollProgress(" in text and "function adoptJobs(" not in text:
        if POLL_OLD not in text or "function langAvailable(code){" not in text:
            return None, ["progress poller is not the expected shape"]
        text = text.replace(POLL_OLD, POLL_NEW, 1)
        text = text.replace("function langAvailable(code){", ADOPT + "function langAvailable(code){", 1)
        # adopt on load, and again whenever the menu is opened
        text = text.replace("drawLangMenu();\n\nlangBtn.onclick=e=>{ e.stopPropagation();\n"
                            "  const open=langMenu.hidden; if(open) drawLangMenu();",
                            "drawLangMenu();\nadoptJobs();"
                            "                                     /* something may already be running */\n"
                            "\nlangBtn.onclick=e=>{ e.stopPropagation();\n"
                            "  const open=langMenu.hidden; if(open){ drawLangMenu(); adoptJobs(); }", 1)
        done.append("adopt running jobs")

    if "A click INSIDE this menu never closes it" not in text:
        if STICKY_OLD not in text or HIDE_OLD not in text or NAV_OLD not in text:
            return None, ["click handler is not the shape the sticky-menu edit expects"]
        text = text.replace(STICKY_OLD, STICKY_NEW, 1)
        text = text.replace(HIDE_OLD, HIDE_NEW, 1)
        text = text.replace(NAV_OLD, NAV_NEW, 1)
        done.append("sticky menu")

    if "refresh button above" not in text:
        text, n = HINT_RE.subn(lambda m: m.group(1) + HINT_NEW + m.group(2), text, count=1)
        if not n:
            return None, ["no no-session hint to reword"]
        done.append("hint")

    if "means that language already exists" not in text:
        text, n = READY_HINT_RE.subn(lambda m: m.group(1) + READY_HINT_NEW, text, count=1)
        if not n:
            return None, ["no can-generate hint to reword"]
        done.append("partial hint")

    # An older generation shows only "translating… mm:ss" with no percentage at all, so there is
    # nothing misleading to fix there — skip the step rather than fail the page for it.
    if "function jobPct(job){" in text and "report the page instead" not in text:
        text, n = JOBPCT_RE.subn(lambda m: JOBPCT_NEW, text, count=1)
        if not n:
            return None, ["jobPct() present but not matchable"]
        done.append("progress %")

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
                          "backup-langrfsh-" + time.strftime("%Y%m%d-%H%M%S"))
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
