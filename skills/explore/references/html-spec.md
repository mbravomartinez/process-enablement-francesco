# HTML page spec

Styling is fixed by `celonis-ui.md` — read it first, then this. Copy the reference
mock's token block and component CSS verbatim; this file governs structure only.

One file. Inline CSS and JS only — no CDN, no external fonts, no fetch, no stock
images. Two images only, both embedded as base64 data URIs: the Celonis mark in the
header and the favicon in `<link rel="icon">` (see `celonis-ui.md`). Must open from `file://`. Start from `../assets/reference-mock.html`: keep
its CSS and JS, replace the content.

Do that by **copying the mock on disk and splicing blocks into the copy** with
`scripts/pe-splice.py`, not by writing the document out whole. The page is ~120 KB and a
render changes only its data blocks; emitting all of it in one call is what loses a render
to a stream timeout. The splicer refuses to write unless every anchor resolved exactly once
and `node --check` parses the result, so the file on disk is always either the previous
page or a complete new one.

The page renders `content.md` (Phase 5) and introduces no fact that isn't there.
Teaching conventions come from `enablement-style.md` — read that first.

## Four hard rules

0. **Tab labels are fixed** (translated, not renamed): Overview · Process
   Step-by-Step · Process Challenges · KPIs · Terminology · Personal Notes.
1. **One thing on screen at a time.** Every tab has a single job. Nothing is
   permanently pinned above the tabs, nothing repeats across tabs, and no screen
   asks the reader to choose what to read first. The knowledge stays complete — it
   is *paced*, not cut.
2. **No pop-ups, modals or dialogs.** Every explanation lives in the frame that
   owns it. Selecting something changes what a frame shows; it never opens a layer.
3. **No Solution stage, anywhere.** The page diagnoses. No remedies, no vendor
   capability claims, no product callouts.
4. **Full sentences, not keywords.** Inputs, outputs, KPI definitions, persona
   accountabilities, object definitions, deviation damage — all prose a newcomer
   can act on. A bare noun phrase in any of those slots is a defect.

## The shell fits the viewport

Everything fits one screen: the window never scrolls, individual components do. Header
and tabs are fixed height, `main` takes the remaining height, and the **active tab pane
is the scroll container**. In the Process tab the linked flow chain is sticky so it
stays visible while the step detail scrolls under it. See `celonis-ui.md` for the
mechanics and the two escapes (print, and narrow screens).

### A reload returns the reader to where they were

A refresh is not a fresh start. The **tab**, the **item selected inside it** (step, problem,
KPI) and that pane's **scrollTop** are written to `localStorage` under
`pe-place-<CURRENT_ID>` and read back on load — saved on tab and pane clicks, on a debounced
pane `scroll`, and on `pagehide` / `beforeunload` / `visibilitychange`. Overview is where a
reader with no stored place lands, not where every reload sends them.

- `localStorage`, **not the URL hash**: this is one reader's place in their own copy of the
  page, and a hash would travel with the file if they sent it on. The key carries
  `CURRENT_ID`, so two explorations — and the same exploration in another language — keep
  their own place.
- An index that no longer exists (the page was regenerated with fewer steps) is ignored, and
  the **open deviation is not restored** — it is the detail of one click, and a page that
  comes back with it already unfolded reads as noise.
- The code sits **inside the synced `notes-engine` span**, after `NOTE_KEY`, because the tabs
  block above it is not synced by `pe-sync-template.py`; it hooks the tab buttons with an
  added `click` listener rather than touching their `onclick`.

## The guided tour — the page explains itself, once

A reader opening an exploration for the first time sees a tabbed document and finds maybe a
third of what it does. So the page walks them through itself: **sixteen steps, one per thing
worth knowing**, switching tabs as it goes — overview, the chain and its deviations, challenges,
KPIs, terminology, the provenance chips, select-a-phrase, the chat, the notes, then the quiz, the
export, and the promise that a reload keeps their place.

The **notes step names both controls on a note card**, because neither announces what it costs:
the circular arrow *adds* a better explanation of one part (it never rewrites the note), and the
bin takes the note **and the highlight it left in the page** with it, with nothing to undo.

Four of the sixteen exist because nothing else on the page states them and a reader who misses
them concludes the feature is broken: **how to switch the chat on** — the circular arrow beside
the status dot finds a Claude session or starts one, green dot and *ready* means live, grey means
none yet, blue means thinking — and **the language switch**, which generates a language once via
Claude, saves it beside the file, reloads instantly thereafter, offers to finish a partial one,
and translates the reader's own notes with it. That step **opens the language menu for real**
while it explains it — a menu described but not shown teaches nothing — by the same path the
globe uses, and closes it again when the reader moves on. Opening happens in the animation frame
*after* the click, because the click that advanced the tour is still bubbling toward the document
listener that shuts every menu. The other two are **the quiz** (ten questions on
its own screen, each answer marked with its reason, then a score ring and a full review; nothing
recorded) and **the export** (PDF through the print dialog for a person, Markdown for an agent,
both with the reader's notes folded into the section they belong to rather than appended).

- **Next-driven, never timed.** The tour switches tabs for the reader but never moves while they
  are reading. An auto-advancing reel is either too fast to follow or too slow to sit through.
- **A coach card, not a modal.** Bottom-left, ~330px, clear of the 320px chat column; the step's
  target takes a 2px accent outline (`.tourspot`) and is scrolled into view. **No dimming and no
  focus trap** — the screen underneath is the thing being explained, and every control on it
  stays live. `role="dialog"` with `aria-live="polite"` on the step text, but never `aria-modal`.
- **Controls:** Back / Next / ✕, *Skip the tour*, `←` `→`, `Esc`. Focus moves to Next on open and
  back to the Guide button on close.
- **Seen once per reader, not once per exploration:** `localStorage['pe-tour-v1']`, set on finish
  *or* dismiss — the tour explains the page, and the page is the same in every exploration. The
  version in the key is what lets a rewritten tour show itself again. A browser with storage
  blocked is treated as *seen*, so a reader who cannot be remembered is never nagged.
- It records the tab it opened on and **returns the reader there** at the end (the place-memory
  restore above runs first, so a first-run tour must not strand them on Notes). It never
  auto-opens for print.
- **The Guide button is created in JS** and inserted into `.hdr-actions` before the Quiz button —
  the same move the selection bar makes. The header markup is not part of any synced region, so
  building the control in the chrome is what lets a stored page acquire the whole feature from
  `pe-sync-template.py` alone, with nothing to hand-edit.
- **The sixteen steps are chrome**, identical on every page and derived from nothing in the
  exploration. A generator neither invents steps nor drops them. The copy sits between
  `/* PE:tour-copy */` and `/* PE:tour-copy-end */`, which `extract_strings()` in
  `chat-bridge.py` walks as its own span, so the tour translates with the rest of the chrome —
  keep those strings plain, double-quoted, and free of newlines so the extractor's filters
  accept them.

### The language menu carries its own Claude refresh

Translation needs a Claude session, and the language menu is where a reader finds that out —
*needs Claude* against every language they cannot have. So the **same refresh control the chat
has sits in the menu header** (`#langRfsh`, same `.rfsh` styling and icon), rather than sending
them across the page to press the other one.

- It sits **on the header row**, right-aligned against the `LANGUAGE` label — a `.lang-hd` flex
  row exists for exactly that, because `.langmenu button` sets `width:100%` and a bare `.rfsh`
  in the menu drops onto a centred line of its own.
- **A click inside the menu never closes it.** Starting a translation, stopping one, pressing
  the refresh, or missing a row are all done while watching the list — closing it under the
  reader hides the progress they just asked for. The handler calls `stopPropagation()` for every
  click it receives, so only the document listener's **outside click** closes the menu, plus
  picking a language that already exists, which navigates away anyway. `langMenu.hidden=true`
  therefore appears exactly once, inside that navigate branch.
- **A pass is no longer all-or-nothing.** Batches run three at a time and used to be discarded
  wholesale if one failed or the reader stopped the run — which is how a translation reported at
  48% left nothing on disk and the row went back to *translate*. `salvage()` now substitutes the
  batches that **did** land, `translate()` writes that as the `.partial` whenever it beats the
  coverage the run started from, and the next attempt resumes from there.
- **A run says what it did, in the log.** Every outcome — start, each pass, a render-check
  rejection, a salvage, a stop, completion — goes through `log_run()` into
  `.chat-bridge.log`. A run answers the page that asked for it, and that page may be gone: a
  reload drops the connection the answer would have travelled down, and an error nobody received
  is what made this look like the work vanishing on its own.
- **A reload must not kill the work.** Two bridge-side rules make the page's adoption
  meaningful, and both were the actual cause of a run "starting over": the **watchdog does not
  retire the bridge while `_translating` is non-empty** — a reload is indistinguishable from a
  close for a moment, and that moment was enough to stop a translation the reader had just
  started — and a bridge that does stop **keeps every `index.<code>.html.partial`** instead of
  deleting it, because `translate()` uses a partial as its base and re-sends only the strings
  still English. `languages_on_disk()` reports those partials, so the menu says *32% — finish*
  rather than *translate*: banked work the reader can see, not work they think they lost.
- **A reload never loses a running translation.** The work happens in the bridge, so a page that
  reloads mid-run has an empty `JOBS` map and used to offer *translate* for the language being
  translated at that moment. On load, whenever the menu opens, and whenever `checkBridge()` finds
  a bridge, `adoptJobs()` asks **`GET /jobs?exploration=…`** what is running for this exploration
  and takes it over: the row shows its percentage and its stop, and the clock starts where the
  run actually started (the bridge reports `elapsed` from the job's `t0`, so nothing restarts at
  0:00). An adopted job is flagged `adopted:true` — it has no fetch of its own waiting on the
  answer, so the **poller** ends it, calling `checkBridge()` for the language's new state and
  redrawing. A job started in this page is left to its own fetch, which still reports coverage
  and passes.
- **A running job reports page coverage, not batches.** `jobPct()` shows where the run started
  plus the share of what was left that has come back — so *80% — finish* climbs 80 → 90 → 99 and
  never restarts at zero — and it is held monotonic, because a pass that achieves less than the
  straight-line estimate would otherwise tick backwards. Counting batches in the current pass
  made a top-up look like it had discarded the 80% and begun the whole page again; it never had
  — `translate()` sends only the strings still verbatim English and applies them on top of the
  existing file.
- The menu's other hint — the one shown when a language *can* be generated — must explain the
  **percentage state** as well as *translate* and *ready*: a row reading *80% — finish* means that
  language already exists but part of it came back in English, and *finish* re-translates only
  those strings, never the page again. Three states appear in the list, so all three are named.
- Inside that hint, `b` stays **inline** (`.langmenu .hint b`). The menu's generic `b` is its
  section label — block, uppercase, indented — so a hint quoting a word from the list above
  (*marked translate*, *offered as ready*) came out as three fragments, each capitalised and
  indented like a heading.
- The menu's no-session hint **names the button** — *"No Claude session yet. Start one with the
  refresh button above, or run `pe-chat .` yourself."* A reader looking at a menu full of *needs
  Claude* should not have to know a shell command to get out of it.
- Both controls call the one `refreshBridge()`, which now spins **both** buttons: pressing
  either should look like something is happening.
- After it settles, the menu is **redrawn**, so a language that read *needs Claude* a moment ago
  reads *translate*.
- The language block sits outside every region `pe-sync-template.py` owns (it follows the quiz),
  so a stored page acquires this part through **`scripts/pe-add-lang-refresh.py`** — idempotent,
  anchored on `'<b>Language</b>'`, which stays English on translated pages because *Language* is
  in the translator's `KEEP_ALWAYS` list.

## Header — the only persistent chrome
Left: the Celonis mark (26×26, data-URI PNG), the title, then **two** `<select>` controls (**Process**, **Industry**,
**Company**) pre-set to this run's values.

Right, as one cluster: a **language icon** (a globe, 36×34, inline SVG) that opens a
dropdown of languages, then **Quiz** and **Export everything as PDF**. Those two actions belong here, beside the language control —
never at the foot of a content tab.

### The header pickers are the page's own dropdown, not the operating system's

A native `<select>` hands its open state to the OS: on macOS the popup is painted in Aqua and
**opens upward over the header**, so the control looks like one thing closed and another thing
open. Both header pickers are therefore **dressed**: a `.selbtn` styled exactly like the closed
control (same border, radius, type, plus a chevron that flips) and a `.selmenu` panel pinned
**below** it — `top: calc(100% + 6px)`, left-aligned, `min-width:100%`, its own scroll past
58vh — with a tick on the current row.

- The `<select>` **stays in the DOM and stays authoritative**. Everything else reads
  `proc.value` / `ind.value` and listens for its `change`; picking a row writes the value and
  dispatches `change`, so switching exploration happens on exactly the path it always did. The
  select is visually hidden, `tabindex="-1"`, `aria-hidden`.
- `fillPicker()` and `syncIndustries()` rewrite `<option>`s in ignorance of the dressing, so a
  **MutationObserver** refreshes the button label, the list, and the disabled state and title —
  rather than those functions being taught to call back.
- The `<label for>` is re-pointed at the button, which also carries the label as `aria-label`;
  `role="listbox"` / `role="option"` / `aria-selected` on the panel, `aria-haspopup` and
  `aria-expanded` on the button. Keyboard: Enter, Space or ↓ opens; ↑ ↓ Home End move; Enter
  picks; Esc and Tab close; an outside click closes any open panel.
- Stored pages get it from **`scripts/pe-dress-selects.py`** (idempotent, anchored on the base
  `select{}` rule and the `fillPicker()` call) — the header and picker code sit outside every
  region `pe-sync-template.py` owns.

### Two selects switch exploration; the company is stated

**Process** lists every process in the registry and **Industry** narrows to the
industries explored for it. Changing either navigates to that exploration's page — `../<path>/<file>`, preferring
the current language, then English, then the entry's first. English is the deliberate
default: every exploration is written in English before it is translated, so it is the
one language a target is almost certain to hold and to read as intended.

The selects are the **only** way to move between explorations — there is no separate
library panel.

**They must list existing pairs only.** An option with no file behind it lands the
reader on `ERR_FILE_NOT_FOUND`. So: the stamped `REGISTRY` carries only explorations
already written to disk; `openExploration` refuses any entry lacking a `path` or
`languages`; and when the project holds one exploration, both selects show their single
option `disabled`, with a title saying it is the only one so far. Never render a
speculative pair, and never render an empty dropdown.

They are driven by a `REGISTRY` constant stamped into the page, because a `file://`
page cannot fetch `$LIB/registry.json`. See `registry.md`.

### Language — generated on demand, then free forever

The dropdown lists the full preselected set, and what a row does depends on what exists:

| Row state | Label | Click |
|---|---|---|
| This file's language | ✓ | nothing |
| Already rendered | *ready* | loads the sibling file (`index.it.html`) instantly |
| Not yet rendered, bridge up | *translate* | **generates it**, then opens it |
| Not yet rendered, no bridge | *needs Claude* | `disabled` — nothing to load and nothing to generate with |

Availability is **not** taken from the stamped `AVAILABLE` list alone: when the bridge answers,
`GET /health` returns the languages actually on disk and the menu uses that. The stamped list is
the offline fallback, which is what keeps an older page from offering a file that was deleted or
missing one that was added.

**Generating a language** POSTs `{lang}` to the bridge's `/translate`, which returns the existing
file instantly if there is one. Otherwise it translates **by dictionary, never by rewriting the
page**:

1. the bridge **extracts** every user-visible string — quoted literals in the JS data blocks plus
   text nodes and reader-facing attributes in the markup — skipping identifiers, colours, codes,
   template fragments and markup;
2. the CLI translates only that **numbered list**, in batches of 80 with three in flight,
   returning `index → text`;
3. the bridge **substitutes mechanically**, longest string first so a short one cannot corrupt a
   longer one containing it, and **escapes for the delimiter each occurrence sits inside** — an
   Italian apostrophe dropped into a single-quoted JS literal would otherwise break the page.

Asking the CLI to rewrite or edit a 100 KB+ page instead is both unreliable and unverifiable: it
translates a handful of strings and stops, and nothing can tell you it is unfinished. With a
dictionary, completeness is **countable** — the response reports strings extracted, translated,
substituted and skipped, and a first pass fails if under 75% come back.

**A page is finished, not repeated.** A language that already exists on disk — rendered, or the
`.partial` an interrupted run left behind — is the base of the next attempt, and only the strings
still verbatim English in it are sent out. Up to `MAX_PASSES` top-up passes run inside one click,
each shrinking the list, stopping when coverage reaches 99.5% or a pass changes nothing. Strings
the translator was *asked about and deliberately returned unchanged* — terms of art, regulation
names, people — are recorded in `index.<lang>.kept.json` and excluded from the denominator; without
that record no page can ever reach 100%.

**Validation before the file is accepted**, in this order: the script must pass `node --check`
(the only check that really answers "is this page usable"); at least 90% of translations must have
substituted; `</html>` present; `CURRENT_LANG` set; and no tab label left in English. A failure
returns the parser's own error and writes nothing.

**Registration, so the language survives the bridge going away.** After writing the file the
bridge records the language in `$LIB/registry.json` and then restamps the `REGISTRY` snapshot in
**every** `index*.html` of **every** exploration in the library. Without this, a page reading its
stamped snapshot offline shows a language that exists on disk as ungenerated — and a page never
lists the language it *is*, so `langAvailable()` always treats `CURRENT_LANG` as available.

The restamp is library-wide, not directory-wide, because each page's snapshot also carries its
**siblings'** languages: that is what a process/industry switch navigates by. Restamping only the
directory that gained the language left every other exploration pointing at the wrong file. And
each entry is matched by its own `path:'<slug>'` — appending to the first `languages:[` in the
file credited whichever exploration sorted first with a language it does not have, which is an
`ERR_FILE_NOT_FOUND` on the next switch. A language whose file is not on disk is dropped from the
snapshot rather than stamped, so a stale registry entry cannot send a reader to a missing page.

**It runs in the background — never behind a modal.** A translation takes minutes, and blocking
the page for them would stop the reader doing the one thing the page is for. Instead the state
lives in the row itself:

- the row's label becomes **`translating… 1:35`** with a live clock, and the reader carries on
  reading, switching tabs, asking the chat;
- **hovering that row reveals a red `✕ stop`** — one click cancels the job, kills the CLI batch,
  keeps nothing, and says so quietly in the chat log;
- clicking the row itself while it runs does nothing, so a second click cannot start a duplicate;
- when it finishes, the row flips to *ready* and a line appears in the chat log — *"Italiano is
  ready (96% translated) — switch to it from the language menu"*. **Do not navigate
  automatically**: the reader did not ask to be moved mid-sentence;
- every failure gets its own sentence in the log (no Claude, already running, incomplete,
  validation rejected, batch failed, timeout, connection lost), never a bare error code.

A language whose file exists but is **unfinished** shows as **`62% — retranslate`**, never
*ready*: `/health` returns `partial` alongside `languages`, and the bridge measures coverage by
counting how many English strings still appear verbatim in the translated file (names and terms
of art excluded, since those are meant to stay). Below 90% the file is set aside as `.partial`
and regenerated rather than served.

**Declare the job table beside the other language state**, before `drawLangMenu()` first runs — a
`const` declared further down the script is in its temporal dead zone at that point, and the
whole script aborts.

### The reader's own notes are translated too

Notes are page content, and a reader switching language must not be left with an Italian page and
English notes. They cannot travel in the file — they live in `localStorage`, per exploration — so
they are translated **on their own path, with the same bargain**: once per language, then cached.

- **The note keeps the language it was written in.** `addNote()` stamps `lang: CURRENT_LANG`, and
  that text is never overwritten. A translation is an **added view**, stored on the note itself as
  `i18n[<code>]` — losing the reader's own words to a language switch would be unforgivable.
- **The chat answers in the page's language.** `/ask` carries `language: CURRENT_LANG`, so a note
  taken on the Italian page is *born* Italian instead of being translated a second later.
- **Everything that renders or exports a note reads a view, never the raw record**: `noteView(n)`
  returns the note as written when the languages match or no view exists yet, and otherwise the
  note with its translated fields merged over it — so a partly translated note falls back
  field by field.
- **Missing views are fetched when a bridge appears**, not on a timer: `checkBridge()` calls
  `translateNotes()`, which POSTs the untranslated notes to `/translate/notes`
  (`{lang, exploration, topic, notes:[{id, question, topic, concept, why, example}]}`) and gets
  `{notes:{<id>:{field:text}}}` back. Nothing is written to disk — the notes belong to the browser,
  and the page saves what comes back into `localStorage`.
- **Asked once.** A note the translator returns unchanged is recorded as an **empty** view, so it
  is never queued again.
- While it runs, one muted line above the notes says *"Translating 3 of your notes into
  Italiano…"*, and a failure says so and leaves the notes as they were taken. Never a modal, never
  a blocked page.
- `langNow()` reads `CURRENT_LANG` inside a `try` on purpose: the first `drawNotes()` runs while
  that `const` is still in its temporal dead zone. The notes pane must render then too — as
  written, which is the right answer before the language is known — and the notes are **drawn
  again** right after `CURRENT_LANG` is declared.

The page never translates itself in the browser. One file per language, generated once.

## Every challenge and every KPI carries a structured example

Strict, for stored pages and generated ones alike. The prose descriptions (Concept,
Challenge, *what it measures*, *why a bad value hurts*, *what starts the clock*, *where it
misleads*) stay exactly as they are; the example is added **beside** them, never instead.

- The field is `example` on the `PROBS` and `KPIS` entries, written as **3–4 `Label: value`
  lines separated by newlines**, the **last line the effect** in currency, days or percent.
- It renders through **one helper, `exampleHTML()`**, shared by `drawProbs()` and
  `drawKpis()`: a `.exlines` grid (`max-content 1fr`) so the values align under each other,
  collapsing to one column under 940px. A line with no colon renders as a value with no
  label, which is how a closing sentence gets in.
- Placement: in Process Challenges, a `stage` headed *"Example — the running case"* between
  Challenge and the root-cause facts. In KPIs, a `lbl` of the same name after *Where it
  misleads* and before the figure.
- Built from the **one running case** the page already uses — same order number, material,
  amounts, dates. A KPI's example shows **its own arithmetic**: standard, actual, variance.
- An **absent field renders nothing**, so a page generated before this rule still draws — but
  a page generated after it is incomplete until every challenge and KPI has one.

## Diagrams — give them room

A diagram that collides with its own labels teaches nothing. Every inline SVG:

- sits in its own `<figure>` with padding and a light background — never inline in a
  paragraph, never sharing a line with text;
- uses a **viewBox tall enough to separate three bands**: event labels above the
  axis, the axis and its zones in the middle, and span labels or zone names below.
  Roughly `660 × 170` for a time axis; add height rather than crowd;
- keeps **at least 20 user units** between any label baseline and the nearest line
  or rectangle, and puts a span's label *below* the span, not on it;
- draws event markers as a tick from well above the axis down to it, with the label
  clear at the top;
- sets `overflow: visible`, `width: 100%`, `height: auto`, and no fixed `height`
  attribute, so the figure scales without clipping;
- centres zone labels under their own zone with `text-anchor="middle"`, and wraps a
  long label onto a second `<text>` line rather than letting it run into its
  neighbour;
- uses `font-size` 12–13, not 10 — this is body text, not a footnote;
- carries a one-line `<figcaption>` saying what the picture shows.

If a label still touches something, the fix is more height, not smaller type.

## Right column — chat — it really answers

A `file://` page cannot start a process, so the chat talks to a **local bridge**:
`scripts/chat-bridge.py`, started by the reader with `pe-chat <exploration-dir>`. The
bridge runs the local `claude` CLI as the **industry-expert agent** against this
exploration's own files and returns the four fields as JSON. Nothing leaves the machine
beyond what the CLI itself sends.

- On load, probe `GET /health` across ports **8787–8789**, preferring a bridge whose
  `dir` basename matches this exploration's folder so two open explorations do not answer
  each other's questions. The header shows a status dot and label: **green + "Claude
  <version>"** when ready, grey + "connecting…" while nothing answers, grey + "no
  Claude" when a bridge answers but has no `claude` on `PATH`. The dot only ever
  *reports*; the refresh control beside it is what acts.
- **Never pre-warn in the log.** A reader opening this page has a Claude session by
  definition, and the orchestrator starts the bridge for them — so a banner announcing
  failure before anything was attempted is noise. Keep the log clean: the status dot
  carries the state, and a message appears only after a real attempt fails.
- **Recover without a reload.** While no bridge answers, re-probe every four seconds, and
  again on window focus and visibility change. A bridge started a minute after the page
  opened must simply start working.
- **A refresh control, immediately left of the status dot** (`button.rfsh#chatRfsh`) —
  a circular-arrow glyph, 18px, quiet until hovered, spinning while it works and
  `disabled` so a second click cannot race the first. It is the reader's way to act on
  what the dot reports, and it does three things in order:
  1. **re-probe now** — `checkBridge({quiet:false})`, instead of waiting out the
     four-second poll;
  2. **have a session started** — if nothing answers, `POST /start`
     `{"exploration":"<folder name>"}` to the **launcher agent** on
     `127.0.0.1:8790` (below), then re-probe for about six seconds;
  3. **say what happened** — a blue `filed` line when Claude comes up, a `sys` line
     naming the fix when it cannot.

  All of its own strings are localised in-page (`RFSH_T`, keyed by `CURRENT_LANG`),
  because it speaks before any translation pass has seen it.

### The launcher agent — how a `file://` page starts a process

It does not: it asks something that already can. `scripts/pe-launchd.py` is a small
always-on daemon on `127.0.0.1:8790`, installed as a login agent by `setup.sh` and
removed by `setup.sh --uninstall-launcher`. `GET /health` reports whether `claude` is on
its `PATH` and which bridges are up; `POST /start` starts one and answers with its port
once it is actually serving.

Three properties the page depends on, and must not work around:
- **It takes a folder name, never a path.** The launcher resolves the name inside the
  library itself and refuses anything that is not a direct child of it holding an
  `index.html`. The page has no say over what runs where — so send `here().path`, and
  never try to send a path.
- **It reuses a bridge that already serves this exploration**, its own or a sibling's,
  rather than starting a second one. A page must treat `already:true` as success.
- **It is optional.** No launcher installed is a normal state, not an error: nothing
  answers on 8790, and the control says so and names `pe-chat <dir>`. Never present the
  agent's absence as a broken page.
- **The session ends when the tab does.** The bridge is a local process started for this
  page, and it must not outlive it. Mint one random session id per page load; while a
  bridge is connected, `POST /beat` with `{"sid"}` every **15 s**; on `pagehide` *and*
  `beforeunload`, send `{"sid"}` to `POST /bye` via `navigator.sendBeacon` — falling back
  to a `keepalive` fetch — exactly once. **And undo it on `pageshow`**: a `pagehide` is not
  always a close — a page put into the back/forward cache fires one and can return minutes
  later — so on `pageshow`, clear the said-goodbye latch, restart the heartbeat, beat once
  immediately and re-probe. Without that the returning page is alive but mute, and the
  bridge retires itself under a reader who is still reading. Beat immediately on
  `visibilitychange` back to visible too: a hidden tab's timers are throttled to roughly one
  call a minute, so the tick that should have gone out while the reader was elsewhere may
  not have. Send both bodies as **`text/plain`**: a beacon
  cannot survive a CORS preflight, and the bridge parses the JSON regardless of the type.
  The bridge waits a few seconds after a goodbye, so a reload (which looks identical) is
  not mistaken for a close, and treats a heartbeat that simply stops as a closed tab —
  which is what a browser crash looks like. When it goes, it takes its `claude`
  subprocesses with it, and leaves every file alone: the exploration, its research,
  finished translations and the reader's notes all survive. Nothing on the page needs to
  warn about this, and nothing may block on it.
- **An ask that cannot be delivered is queued, never refused.** No bridge yet, no
  `claude` behind the bridge, or a connection lost before the answer arrived — in every
  one of those cases the ask is written to `pe-pending-<id>` in `localStorage` and shown
  in the log as itself: the question, and the fact that it is waiting, with a control to
  drop it. **All three ways in behave the same way** — a typed question, a selected phrase
  and a note refinement — and each stores what it needs to be replayed: the selection path
  its anchor, so a phrase queued now still highlights when the answer lands later, and the
  refine path the id of the note it belongs to, so the answer is added to that card rather
  than filed as a new note. A refinement whose note was deleted while it waited is dropped
  with a line saying so, never filed as a stray note. The moment a bridge
  becomes reachable — the reader clicked refresh, or the four-second probe found one —
  the queue drains **oldest first**, and each answer is rendered and filed under the
  section and item it was originally asked from, not wherever the reader has since
  wandered. A drain stops at the first ask it cannot deliver and leaves that ask, and
  everything behind it, queued; it never reorders and never asks the same entry twice.
  Whatever is still waiting is redrawn on load, because a reader who got no answer is
  exactly the reader who reloads.
- On submit, `POST /ask` with the question plus `process`, `industry`, `company`,
  `section` and `item` — so the expert knows where the reader was standing — and
  `language: CURRENT_LANG`, so the fields come back in the language the reader is
  reading and the notes are filed in it.
- **The reply is `{"notes":[…]}` — one note per concept, and each becomes its own
  Personal Note.** A reader who asked about three things asked three questions: three
  short notes they can each find later beat one long note they must re-read to use.
  Render each as its own `.msg.ai` card, marked *"n of m"* when there is more than one,
  and call `addNote` once per note so each is filed separately. Then one `filed`
  confirmation naming the count, not one per note. A bare four-field object is still
  accepted and rendered as a single note — an older bridge is a normal thing to be
  talking to, and a reader must never see a question fail over a shape.
- While waiting: a muted "Asking the <industry> expert…" line, a blue dot, and the input
  disabled. Never leave a question with no acknowledgement.
- **Say the truth when it cannot answer.** No Claude in the environment → say exactly
  that and name the fix (`pe-chat .`). Never fabricate an answer, never fake a delay.
- The answer renders in the note's fields and is filed to Personal Notes
  immediately, with the blue confirmation line.

Fixed panel headed *"Chat — ask infos"*, a scrolling log, a composer.

The opening message must **tell the reader where the value goes**: anything useful in an
answer is written into their Personal Notes, tagged with the screen and item they were
on. After each exchange, a small blue confirmation line appears in the log — *"Filed in
Personal Notes — Process Step-by-Step · Record Goods Issue"* — so nothing is saved
invisibly.

Every answer is returned in the note's two fields — **an explanation** and **an example**
using the running case — because the answer and the note are the same artefact; the agent is
instructed to return exactly that JSON shape (`{topic, what, example}`).

**There is no "why it matters" field.** The reader asked to understand one thing, not to be
told it is important, and a third section is where a note turns into an essay. Where the
consequence really is part of the answer it is the last clause of a sentence. Notes filed
before this rule carry a `why` and the page still renders it — an old note is not made wrong
by a new rule — but nothing new sends one, and both the chat and the note card render only
the fields an answer actually has.

**A note is short and its example is structured.** The reader files the answer to re-read in
a hurry, so `what` is two or three short sentences (55 words at the outside) and the whole
note about 90 words, never past 120. `example` is **not a paragraph**: three to five short lines,
separated by real newlines in the JSON string, each a label and its value, the last stating
the effect —

    Standard: material 100234, plant 1100, lot size 5,000 kg, €150 setup → €0.03/kg
    Order:    900045678, 4,000 kg planned, 3,850 kg good output
    Effect:   €150 over 3,850 kg = €0.039/kg → €0.009/kg lot size variance

Those breaks are content, so the note fields, the refinement values and the chat's own
rendering all set `white-space:pre-line`, and the translator is handed them escaped
(`\n`) with instructions to keep every one — a numbered batch would otherwise read the
tail of a value as a line of its own.

## Selecting a phrase — ask the page, not just the chat

The chat answers typed questions. A reader can also **select any phrase in a content
panel** and ask for an *explanation* or a *worked example* of it. The answer arrives in the
chat and files as a Personal Note exactly as a typed question does, and the phrase stays
highlighted with a control that jumps to the note.

**Scope: content panels only** — `overview`, `process`, `problems`, `kpis`, `glossary`.
Never the SVG flow (it has no wrappable text nodes), never the chat log, never the quiz.

**The bar has two states.** Choosing *Explain* or *Generate example* does not send the
request — it turns the bar into a **text field** where the reader says what they actually
want cleared up, with *Ask* / *Cancel*, Enter to submit and Escape to abandon. "Explain
this" alone makes the expert guess which part lost them; this removes the guess. **Typing
is optional** — an empty field is the plain "explain this phrase" request, and nothing in
the UI should imply the reader owed more.

Three consequences the implementation must handle, all of them because focusing an input
destroys the document selection:
- the collapse-hides-the-bar rule and the window `blur` rule **stand down while composing**
  (`selComposing`), or the bar closes the instant the field takes focus;
- the bar's `mousedown` `preventDefault` — which keeps the selection alive — must **exempt
  the input**, or it can never take focus;
- the bar is placed **above where the phrase begins**, its left edge on the first pixel of the
  first line's rect (`range.getClientRects()[0]`), whichever direction the drag ran, clamped to
  the viewport. It must **not** follow the cursor to the end of the selection: right-aligning the
  bar on the last line reads well only while that line ends far to the right, and a wrapped
  phrase whose tail is short ("…carries / the cost.") drags the bar's own width leftwards out of
  the text column, over the sidebar and on top of a line still being read. The start of a phrase
  is always at the column's left edge and always in the same place, so the reader learns one spot
  to look. If there is no room above the first line, the bar goes **under the last** one — never
  over the phrase it is asking about. An engaged bar keeps that position:
  it is never re-placed by a scroll (typing past the field's width scrolls the input, which
  would otherwise re-measure against a selection that no longer exists), and `placeSelbar`
  ignores an all-zero rect rather than computing a corner from it;
- the phrase is **marked provisionally** while the reader types (same yellow, no `↗`, since
  there is no note to jump to yet), so they can still see what they are asking about. It is
  cleared on cancel, on an outside click, and replaced by the real highlight on success.

**A selection returns exactly ONE note.** `POST /ask` carries `selection` and
`mode: explain | example`; the bridge appends its selection instructions and holds the
reply to one note, and the page slices to one as well. A selected phrase is one concept by
definition — splitting it would invent concepts the reader never asked about, and each note
is filed separately in their notebook. `mode` shifts which field carries the answer
(`what`/`why` for *explain*, `example` for *example*), never the note's shape. `detail`
carries the reader's own words and **outranks both**: the phrase says what they are looking
at, the mode says which kind of help they want, and `detail` says which part actually lost
them — an answer that explains the phrase correctly but not the part they asked about has
missed. The note's `question` records the phrase and their words together, so the notebook
shows what was actually asked.

### Highlights are derived from notes, never stored

`anchor` is an **optional** field on a note. A note born from a selection has one; a note
asked in the chat has none, and most notes are that kind — a chat-born note is an ordinary
note with nothing on the page to point back to, not a highlight that failed to render.

So the highlights on screen are simply `NOTES.filter(n => n.anchor)`, re-resolved on every
draw and grouped by `(tab, item, quote)`. Nothing else has to be kept in step:

- **Delete a note and its highlight goes with it** — there was never a second object.
- **Two notes may share one phrase** (an explanation *and* an example), so a highlight
  lives as long as **any** note in its group does, and its control opens all of them.
- **Selecting a phrase that already has notes offers only the missing mode**; a phrase with
  both offers the way back to them instead. At most two notes per phrase.

### The note card is a closed row until opened

A reader who has asked thirty questions has a list to scan, not thirty essays to scroll
past. So a note card renders **collapsed**: the anchor line (note number, section · item,
*from the page*, timestamp, refine and delete) and the **topic, which is the toggle** —
chevron, `role="button"`, `tabindex="0"`, `aria-expanded`, Enter and Space as well as click.
Everything else (*you asked*, the fields, the refinements) sits in a `.nbody` that is
`hidden` until opened.

- Cards are **wider than a prose column** — about `70em` — precisely because the point of
  the extra width is the same text in fewer lines.
- Open state is held **in memory, by id**, not in storage: it belongs to this sitting with
  the page, and a redraw (a refinement landing, a language switch) must not close a card the
  reader is reading.
- Three things open a card on their own: **the note you just asked for**, **a note that just
  received a refinement**, and **a note jumped to from a highlight in the page**. Anything
  else stays closed until the reader asks.
- The *from the page* control carries the **highlight's own yellow** (`#fdf07a`, `#ffd93d` on
  hover), because that is what it takes you to — the phrase still marked in the page. A
  neutral chip made the reader guess where the button led.

### Refining a note

A note can be right and still leave one thing unclear. Every note card carries a **refine
control beside its delete button**: it opens a field *inside that card* where the reader says
what should be explained better, so they never have to find the phrase again and re-ask.

- **Every block of the note carries its own refine control too** — one on the explanation, one
  on *why it matters*, one on the example, and one on each follow-up already filed. A reader
  who wants the example redone should not have to write a sentence explaining that they mean
  the example: the control they clicked says it. The block controls sit on the block's own
  label at about a third opacity and come to full strength when the pointer or the keyboard
  reaches that block, so a note still reads as prose. The header control keeps its old
  meaning — the note as a whole.
- The request sends the **note itself** (`refine: {topic, question, what, why, example}`), so
  the expert answers the follow-up in the context of what the reader has already been told
  instead of starting over. When one block was aimed at, it also sends **`part`** (what the
  reader saw on the control: `Explanation`, `Why it matters`, `Example`, `your follow-up`) and
  **`focus`** — that block's current text. The bridge then instructs the expert to improve
  that part *and only that part*; rewriting the example when the explanation was asked about
  is the failure this exists to prevent. `part` absent means the whole note, which is what an
  older page sends, so the server side stays backward compatible. It returns **one note**,
  held to that server-side like a selection is.
- The answer is **appended to the note as a refinement**, never merged into its fields and
  never a rewrite: `{ask, part, topic, what, why, example, when, lang}` — `part` is kept so the
  card can say *You also asked about the Example*, and so a queued refinement lands on the
  same block when it drains. Refinements accumulate,
  newest last, each labelled with what was asked — the follow-up is its own small thing, and
  it belongs next to the concept it clarifies. Empty `why`/`example` are not rendered, so a
  one-sentence answer looks like one sentence.
- **The ask is echoed into the chat**, exactly as a typed question or a selection is: a `me`
  bubble naming what is being refined — the block and the note's topic, *Refining Example of
  Goods Receipt* — with the reader's own words beneath it,
  then the same `think` indicator with its seconds ticker until the answer lands, and finally
  the *Added to your note* line. A refine that only greys out its own button looks like
  nothing happened — the chat is where the reader watches for a reply.
- Deleting the note takes its refinements with it; they live on the note, not beside it.
- Only one refine field is open at a time — a card has one field, whichever control opened it,
  and it says which part it is aimed at (label and placeholder both). An empty ask sends
  nothing.
- Refinements render **as written**. The note's own fields have an i18n cache and follow the
  page's language; a refinement is the reader's own follow-up, so it stays in the language it
  was asked in.

### Anchoring, and why it cannot be a DOM mutation

Panels are rebuilt by `innerHTML` on every step, problem and KPI change, which destroys an
inserted `<mark>`. So an anchor is a **text-quote selector** — `{tab, item, quote, prefix,
suffix, occurrence}` — re-resolved against the panel's flattened text after every draw, and
a `MutationObserver` on the panes triggers that rather than each draw function being hooked
(including the ones added later). Marking splits text nodes, so a phrase spanning several
elements becomes several `<mark>`s and one control after the last of them.

**The observer must be switched off while marking.** Marking mutates the very panes the
observer watches, so an observer left connected re-fires on its own work and schedules
another draw, forever. The symptom is not a slow page but a dead control: the `↗` button is
destroyed and rebuilt several times a second, so a press never survives to become a click.
`drawHighlights` disconnects it for the duration and discards the queued records
(`takeRecords`) before reconnecting.

**Watch `hidden`, not only content.** Switching tab toggles a pane's `hidden` attribute and
changes nothing inside it, so an observer watching `childList` alone never learns the pane
came back into view: the reader reloads, clicks through to their note's tab, and the phrase
is not highlighted even though the note is right there — until something happens to rebuild
the panel. `attributeFilter:['hidden']` closes that. Marking never touches `hidden`, so it
cannot feed back into itself.

**A quote that cannot be placed confidently highlights nothing.** Prefix and suffix settle
which occurrence was meant; the occurrence index is the last resort. Highlighting the wrong
words teaches the reader something false, which is worse than highlighting nothing.

**A paragraph is a legitimate selection, and it is highlighted like a phrase.** The limit is
**1500 characters** for both asking and marking. It used to be 300 for both, which rejected a
whole paragraph outright — no selection bar at all, indistinguishable from the page ignoring the
reader — and an intermediate version kept marking at 300 while allowing the ask, which answered
the question but left the reader told *whole passage · not highlighted*. Neither is necessary:
marking a 332-character paragraph marks every character with one jump control, and an
894-character selection spanning three paragraphs becomes three marks and still one control,
stable across redraws. So there is **one limit**, and the real guard is the existing one — a
quote that cannot be placed confidently highlights nothing. Two consequences still to honour:
what is **shown** (the note heading, the chat echo) is a clipped stand-in of ~160 characters
ending in an ellipsis on a word boundary, because a paragraph is an unusable heading, while what
is **sent** is the passage entire — and past 300 characters the bridge tells the expert it has a
passage rather than a phrase, so `topic` is a label it writes rather than the passage echoed
back.

### On a translated page

An anchor names the words the reader selected, so on `index.<lang>.html` it names a phrase
that is not there. The note itself is translated, so **its translated topic is the one
phrase to look for — and only when it is unambiguous in that panel** (present exactly
once, six characters or more). Anything less confident highlights nothing. A match that
succeeds is cached on the note under `anchor.byLang.<lang>`, so the search runs once per
note per language and every later draw is deterministic rather than re-guessing.

Store the anchor **by value**: resolving caches onto the anchor, and two notes must never
share one mutable object.

### One highlighter colour

STABILO BOSS yellow for every highlight. Which kind of note it produced is carried by the
control's tooltip, not by colour — a second colour would be a code the reader has to be
taught, and the page never teaches it.

## No footer
No takeaway cards and no closing summary. The page ends with the content. The quiz exists
only as its own overlay frame, opened from the header's **Quiz** button — never as a
strip at the bottom of a content tab.

## Provenance — three states, always visible

A reader must be able to tell whose words they are reading:

| State | Rendered as | Means |
|---|---|---|
| From the customer's own material | `<span class="src ctx">from your context</span>` — blue chip | their handbook, glossary or KPI definition said this |
| Industry-generic, pending confirmation | `<span class="src typ">typical</span>` — grey chip | nobody has confirmed it for this account |
| Researched but unconfirmed | `[unverified]` / `[inferred]` inline | one source, or an inference |

When context is supplied, the Terminology tab opens with a one-line key explaining the
two chips. Chips go on the item they qualify — a term, a system, a step name, a KPI
definition — never on a whole section. **Never remove a chip to make the page look more
authoritative**, and never leave a `typical` chip on something the customer's material
actually named.

See `user-context.md` for what the customer's material settles and what it does not.

## Accessibility & layout
`aria-selected` on tabs, `aria-current` on the selected step, problem and KPI;
the quiz screen receives focus at the top when opened and returns the reader to the
tabs on exit;
keyboard-focusable flow nodes and list items. The two-column grid collapses to one
under 940px; the flow chain scrolls horizontally rather than wrapping into
ambiguity. Colour is never the only carrier of meaning — object colours are always
paired with the object's name.
