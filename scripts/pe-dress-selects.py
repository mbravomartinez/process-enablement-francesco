#!/usr/bin/env python3
"""Replace the header's native <select> popups with the page's own dropdown, in stored pages.

A native `<select>` hands its open state to the operating system: on macOS it paints an Aqua
popup that can open UPWARD over the header and looks nothing like the closed control it came
from. The closed control is right, so this dresses the open one to match — same border, radius
and type — and pins it below the button.

The `<select>` elements stay in the DOM and stay authoritative: `proc.value`, `ind.value` and
their `change` listeners are untouched, and picking a row writes the value and dispatches
`change`, so switching exploration happens exactly as before. `fillPicker()` and
`syncIndustries()` go on rewriting `<option>`s in ignorance of the dressing — a MutationObserver
refreshes the button and the list.

Two edits, both idempotent, both anchored on code rather than prose so a translated page patches
like an English one:

  1. the CSS, after the base `select{...}` rule;
  2. the `dressSelect()` enhancer, after the `fillPicker()` call that first fills those selects.

    pe-dress-selects.py [--library DIR] [--check] [FILES...]
"""
import argparse, glob, os, re, shutil, sys, time

CSS = '/* ---- the header pickers, dressed ----\n   A native <select> hands its open state to the operating system: on macOS it paints an Aqua\n   popup that can open UPWARD over the page and looks nothing like the closed control it came\n   from. The closed control is right, so the open one is built to match it — same border, same\n   radius, same type — and it always opens downward, under the button.\n   The <select> itself stays in the DOM as the source of truth: everything else reads\n   `proc.value` / `ind.value` and listens for its `change`. */\n.selwrap{position:relative;display:inline-flex}\n.selwrap select{position:absolute;width:1px;height:1px;padding:0;margin:0;opacity:0;\n pointer-events:none;clip:rect(0 0 0 0);overflow:hidden;border:0}\n.selbtn{font:inherit;font-size:13px;display:inline-flex;align-items:center;gap:8px;\n padding:5px 8px;border:1px solid var(--line);border-radius:4px;background:#fff;\n color:var(--ink2);cursor:pointer;max-width:280px}\n.selbtn:hover:not([disabled]){border-color:var(--ink2)}\n.selbtn[aria-expanded=true]{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}\n.selbtn:focus-visible{outline:2px solid var(--accent);outline-offset:1px}\n.selbtn[disabled]{cursor:default;color:var(--muted);background:#fafafb}\n.selbtn .sv{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}\n.selbtn svg{width:9px;height:9px;flex:none;margin-left:auto;stroke:var(--muted);fill:none;\n stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round;transition:transform .12s ease}\n.selbtn[aria-expanded=true] svg{transform:rotate(180deg)}\n/* opens downward, always: left-aligned under the button, never over the header */\n.selmenu{position:absolute;top:calc(100% + 6px);left:0;z-index:65;min-width:100%;\n max-height:min(58vh,380px);overflow-y:auto;background:#fff;border:1px solid var(--line);\n border-radius:6px;box-shadow:0 12px 32px rgba(26,26,31,.14);padding:4px;white-space:nowrap}\n.selmenu[hidden]{display:none}\n.selmenu button{display:flex;gap:10px;align-items:center;width:100%;text-align:left;font:inherit;\n font-size:13.5px;background:none;border:0;border-radius:4px;padding:7px 9px;cursor:pointer;color:var(--ink2)}\n.selmenu button:hover,.selmenu button.here{background:var(--line2)}\n.selmenu button[aria-selected=true]{color:var(--accent);font-weight:600}\n.selmenu .tick{margin-left:auto;color:var(--accent);visibility:hidden}\n.selmenu button[aria-selected=true] .tick{visibility:visible}\n'

JS = '\n/* ---- dress the two pickers -----------------------------------------------------------\n   The native popup is the operating system\'s, not the page\'s: on macOS it opens upward over\n   the header and is painted in Aqua, so the control looks like one thing closed and another\n   thing open. This puts a button and a list in front of it, styled like the closed control and\n   always opening downward.\n\n   The <select> stays and stays authoritative — `proc.value`, `ind.value` and the `change`\n   listeners above are untouched; picking an item writes the value and dispatches `change`, so\n   the switch happens exactly as it always did. `fillPicker()` and `syncIndustries()` keep\n   rewriting <option>s in complete ignorance of this, which is why a MutationObserver refreshes\n   the label and the list rather than those functions being taught to call back. */\nfunction dressSelect(sel){\n  if(!sel || sel.dataset.dressed) return;\n  sel.dataset.dressed=\'1\';\n  /* read the label before the select moves — afterwards it is no longer its sibling */\n  const label=sel.id?document.querySelector(\'label[for="\'+sel.id+\'"]\'):null;\n  const wrap=document.createElement(\'div\'); wrap.className=\'selwrap\';\n  sel.parentNode.insertBefore(wrap,sel); wrap.appendChild(sel);\n  sel.tabIndex=-1; sel.setAttribute(\'aria-hidden\',\'true\');\n\n  const btn=document.createElement(\'button\');\n  btn.type=\'button\'; btn.className=\'selbtn\'; if(sel.id) btn.id=sel.id+\'Btn\';\n  btn.setAttribute(\'aria-haspopup\',\'listbox\'); btn.setAttribute(\'aria-expanded\',\'false\');\n  btn.innerHTML=\'<span class="sv"></span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>\';\n  const menu=document.createElement(\'div\');\n  menu.className=\'selmenu\'; menu.setAttribute(\'role\',\'listbox\'); menu.hidden=true;\n  wrap.append(btn,menu);\n  /* the label pointed at the select; it points at the button now, so clicking it still opens\n     the thing the reader can see */\n  if(label){ label.htmlFor=btn.id; btn.setAttribute(\'aria-label\',label.textContent.trim()); }\n\n  let at=-1;                                    /* the option the keyboard is on */\n  const opts=()=>[...sel.options];\n  function paint(){\n    btn.querySelector(\'.sv\').textContent=sel.value||\'—\';\n    btn.disabled=sel.disabled;\n    btn.title=sel.title;\n    menu.innerHTML=opts().map((o,i)=>\n      `<button type="button" role="option" data-i="${i}" aria-selected="${o.value===sel.value}">`\n      +`<span>${chatEsc(o.textContent)}</span><span class="tick">✓</span></button>`).join(\'\');\n  }\n  function mark(){\n    [...menu.children].forEach((b,i)=>b.classList.toggle(\'here\',i===at));\n    const on=at>=0?menu.children[at]:null;      /* absent in some embedded webviews */\n    if(on&&on.scrollIntoView) on.scrollIntoView({block:\'nearest\'});\n  }\n  function open(){\n    if(sel.disabled) return;\n    closeAllSelMenus(menu);\n    paint(); menu.hidden=false; btn.setAttribute(\'aria-expanded\',\'true\');\n    at=opts().findIndex(o=>o.value===sel.value); mark();\n  }\n  function close(){ menu.hidden=true; btn.setAttribute(\'aria-expanded\',\'false\'); at=-1; }\n  function pick(i){\n    const o=opts()[i]; close(); btn.focus();\n    if(!o||o.value===sel.value) return;         /* same value — nothing to announce */\n    sel.value=o.value;\n    sel.dispatchEvent(new Event(\'change\',{bubbles:true}));\n  }\n  btn.onclick=e=>{ e.stopPropagation(); menu.hidden?open():close(); };\n  btn.onkeydown=e=>{\n    if(e.key===\'ArrowDown\'||e.key===\'Enter\'||e.key===\' \'){ e.preventDefault(); open(); }\n  };\n  menu.onclick=e=>{ e.stopPropagation();\n    const b=e.target.closest(\'[data-i]\'); if(b) pick(+b.dataset.i); };\n  wrap.addEventListener(\'keydown\',e=>{\n    if(menu.hidden) return;\n    const n=opts().length;\n    if(e.key===\'Escape\'){ e.preventDefault(); close(); btn.focus(); }\n    else if(e.key===\'ArrowDown\'){ e.preventDefault(); at=(at+1)%n; mark(); }\n    else if(e.key===\'ArrowUp\'){ e.preventDefault(); at=(at-1+n)%n; mark(); }\n    else if(e.key===\'Home\'){ e.preventDefault(); at=0; mark(); }\n    else if(e.key===\'End\'){ e.preventDefault(); at=n-1; mark(); }\n    else if(e.key===\'Enter\'||e.key===\' \'){ e.preventDefault(); if(at>=0) pick(at); }\n    else if(e.key===\'Tab\'){ close(); }\n  });\n  sel.addEventListener(\'change\',paint);\n  new MutationObserver(paint).observe(sel,{childList:true,attributes:true,\n    attributeFilter:[\'disabled\',\'title\']});\n  paint();\n}\nfunction closeAllSelMenus(except){\n  document.querySelectorAll(\'.selmenu\').forEach(m=>{\n    if(m===except||m.hidden) return;\n    m.hidden=true;\n    const b=m.previousElementSibling; if(b) b.setAttribute(\'aria-expanded\',\'false\');\n  });\n}\ndocument.addEventListener(\'click\',()=>closeAllSelMenus());\n[proc,ind].forEach(dressSelect);'


def patch(text):
    """-> (new_text or None, [what changed] or [why not])"""
    done = []
    if ".selwrap{" not in text:
        m = re.search(r"^select\{font:inherit[^\n]*\n", text, re.M)
        if not m:
            return None, ["no base select{} rule to anchor the CSS to"]
        text = text[:m.end()] + CSS + text[m.end():]
        done.append("css")
    if "function dressSelect(" not in text:
        m = re.search(r"^fillPicker\(\);$", text, re.M)
        if not m:
            return None, ["no fillPicker() call to anchor the enhancer to"]
        text = text[:m.end()] + JS + text[m.end():]
        done.append("enhancer")
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
                          "backup-selects-" + time.strftime("%Y%m%d-%H%M%S"))
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
