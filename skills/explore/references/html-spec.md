# HTML page spec

Styling is fixed by `celonis-ui.md` — read it first, then this. Copy the reference
mock's token block and component CSS verbatim; this file governs structure only.

One file. Inline CSS and JS only — no CDN, no external fonts, no fetch, no stock
images. Two images only, both embedded as base64 data URIs: the Celonis mark in the
header and the favicon in `<link rel="icon">` (see `celonis-ui.md`). Must open from `file://`. Start from `../assets/reference-mock.html`: keep
its CSS and JS, replace the content.

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

## Header — the only persistent chrome
Left: the Celonis mark (26×26, data-URI PNG), the title, then **two** `<select>` controls (**Process**, **Industry**,
**Company**) pre-set to this run's values.

Right, as one cluster: a **language icon** (a globe, 36×34, inline SVG) that opens a
dropdown of languages, then **Quiz** and **Export everything as PDF**. Those two actions belong here, beside the language control —
never at the foot of a content tab.

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
  Claude" when a bridge answers but has no `claude` on `PATH`.
- **Never pre-warn in the log.** A reader opening this page has a Claude session by
  definition, and the orchestrator starts the bridge for them — so a banner announcing
  failure before anything was attempted is noise. Keep the log clean: the status dot
  carries the state, and a message appears only after a real attempt fails.
- **Recover without a reload.** While no bridge answers, re-probe every four seconds, and
  again on window focus and visibility change. A bridge started a minute after the page
  opened must simply start working.
- **The session ends when the tab does.** The bridge is a local process started for this
  page, and it must not outlive it. Mint one random session id per page load; while a
  bridge is connected, `POST /beat` with `{"sid"}` every **15 s**; on `pagehide` *and*
  `beforeunload`, send `{"sid"}` to `POST /bye` via `navigator.sendBeacon` — falling back
  to a `keepalive` fetch — exactly once. Send both bodies as **`text/plain`**: a beacon
  cannot survive a CORS preflight, and the bridge parses the JSON regardless of the type.
  The bridge waits a few seconds after a goodbye, so a reload (which looks identical) is
  not mistaken for a close, and treats a heartbeat that simply stops as a closed tab —
  which is what a browser crash looks like. When it goes, it takes its `claude`
  subprocesses with it, and leaves every file alone: the exploration, its research,
  finished translations and the reader's notes all survive. Nothing on the page needs to
  warn about this, and nothing may block on it.
- On submit, `POST /ask` with the question plus `process`, `industry`, `company`,
  `section` and `item` — so the expert knows where the reader was standing — and
  `language: CURRENT_LANG`, so the four fields come back in the language the reader is
  reading and the note is filed in it.
- While waiting: a muted "Asking the <industry> expert…" line, a blue dot, and the input
  disabled. Never leave a question with no acknowledgement.
- **Say the truth when it cannot answer.** No Claude in the environment → say exactly
  that and name the fix (`pe-chat .`). Never fabricate an answer, never fake a delay.
- The answer renders in the note's three fields and is filed to Personal Notes
  immediately, with the blue confirmation line.

Fixed panel headed *"Chat — ask infos"*, a scrolling log, a composer.

The opening message must **tell the reader where the value goes**: anything useful in an
answer is written into their Personal Notes, tagged with the screen and item they were
on. After each exchange, a small blue confirmation line appears in the log — *"Filed in
Personal Notes — Process Step-by-Step · Record Goods Issue"* — so nothing is saved
invisibly.

Every answer is returned in the note's three fields (**what it is**, **why it matters**,
**an example** using the running case), because the answer and the note are the same
artefact — the agent is instructed to return exactly that JSON shape.

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
