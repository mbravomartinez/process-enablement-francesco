---
name: explore
description: SKILL (engine behind /process-enablement:start) — you normally want that command instead. Builds the self-contained HTML enablement page for a process at a company, in a chosen language. Also triggers on "explore the <process> process at <company>" or a process primer before a discovery workshop.
---

# Process Exploration

Turn three inputs — **process**, **company**, **language** — into one
self-contained HTML page a Value Engineer can read before a discovery workshop, or
share as a primer.

## Never emit a large file in one tool call

Every artifact this pipeline produces is big: three research returns of 20–40 KB each,
`content.md` at 40–60 KB, and a rendered page at ~120 KB. Written in one call, each of
those keeps a stream silent for minutes, and a client idle timeout (observed in practice
at 180 s) drops the response and loses the whole file — after which the retry is just as
long and fails the same way. The run stalls indefinitely on exactly the phases that
matter most.

So the rule for this whole run: **no single write larger than roughly 8 KB.** Build big
artifacts from small pieces on disk instead, using the two helpers in `scripts/`:

| Artifact | How it gets written |
|---|---|
| `research/*.md` | **the researcher writes its own file** and returns a short digest — the payload never passes through the orchestrator (Phase 3) |
| `content.md` | one section per call via `pe-parts.sh`, then assembled (Phase 5) |
| `index.html` | `pe-splice.py` replaces data blocks inside a disk copy of the mock (Phase 6) |
| `registry.json`, restamps | `library.sh` and `pe-splice.py`, never a hand-written whole file |

Two properties matter more than the byte count. **Every piece is retryable on its own** —
`pe-parts.sh put` overwrites the part of the same name, so a dropped section costs that
section and nothing else. And **a partial artifact never reaches the library** —
`pe-splice.py` writes only after every anchor resolved and the JS parsed, so there is no
state where a half-rendered page looks finished.

If a stream does drop mid-phase, do not restart the phase. Run `pe-parts.sh list` (or
diff the page against the mock) to see what already landed, and resume from the first
missing piece.


## The template is the page — every change reaches every exploration

**A change to the page's shared chrome is not finished until every page in the library
carries it.** Not the mock alone, not the newest exploration alone: all of them. A
library where the same control behaves differently on two pages is not a library, and a
reader who clicks refresh on last month's exploration must get exactly what this
month's does.

This is a rule about *where you edit*, and it has two halves.

**Edit the template, never the stored page.** `assets/reference-mock.html` is the single
source of the chrome — the chat, the bridge probe, the refresh control, the status dot
and their CSS. Fix a bug there. Then run:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/pe-sync-template.py"            # push it to the library
python3 "$CLAUDE_PLUGIN_ROOT/scripts/pe-sync-template.py" --check    # report drift, write nothing
```

It replaces each chrome region in every `index*.html` from the template, gated by
`node --check`, keeping the previous versions in a stamped backup. Run `--check` after any
chrome change; a `drift` line means the work is not done yet.

**Do not try to re-render a stored page from the template.** The tempting version of this
rule — "regenerate old pages from the latest template" — would destroy them. A page is
~99% template by line count, but each one also carries 80–100 lines of its own markup and
200–265 lines of its own code: the prose of its Overview, its document-card renderers,
consts the template has never heard of, all of it derived from research and the customer's
own material. None of that is reproducible from a template. So the page is two layers and
only one is owned centrally:

| Layer | Who owns it | On a sync |
|---|---|---|
| **Chrome** — chat, bridge, refresh, status dot, the notes engine, the selection/highlight engine, their CSS | the template | replaced wholesale |
| **Exploration** — data blocks, prose, per-page renderers, per-page CSS | that exploration | never touched |

The notes engine is in that list because of a real miss: the selection feature taught
`addNote` to accept an anchor, but `addNote` sat *outside* every synced region, so each
stored page kept its own two-argument copy and silently dropped the anchor — the feature
worked in the template and nowhere else. Verified across the library as pure chrome (no page
declares anything of its own inside that span) and widened into the sync. When a change
cannot be expressed inside a region, that is the signal to widen the region, not to
hand-edit the pages.

It happened a second time with the same feature: the refine control's **CSS** was written into
the note style block, which no region covered. The JS reached every page and the styling did
not, so the control rendered as unstyled empty boxes everywhere except the template — a
failure that looks like a missing feature, not like missing CSS. `notes-css` was added for it.
The lesson to carry: after any chrome change, check that **both** halves of it — behaviour and
appearance — fall inside a synced region, because `--check` can only report drift in the
regions it knows about.

If a chrome change cannot be expressed inside a synced region, that is a signal the region
boundaries are wrong — widen them in `pe-sync-template.py` and sync again. Never hand-edit
seven pages; the next change would have to find them all over again.

Two consequences worth knowing before you edit:
- **A synced region must be self-contained.** It is copied verbatim into pages that already
  declare their own names, so a helper the region needs is declared *inside* it, prefixed
  to keep it clear of the page's own (`chatEsc`, not `esc` — the pages already have an
  `esc`).
- **Translated pages come back to English chrome.** `index.<lang>.html` holds the chrome
  with its labels translated; a sync restores the template's English until the next
  translate pass. The tool names every page this affects. Stale *code* on a translated page
  is a broken control; an English status label is cosmetic — so sync, then re-translate.

## Phase 0 — Check the library first

Resolve the library before reading anything. Run
`"$CLAUDE_PLUGIN_ROOT/scripts/setup.sh" --quiet` — it is idempotent, creates the library
and its registry on a first run, and prints `LIB<TAB><dir>`. **That directory is `$LIB` for
the rest of the run**; never assume a path for it, and never write outside it. Stop on a
`BLOCKED` line. (When `/process-enablement:start` dispatched this skill it already ran the
preflight — reuse the `$LIB` it printed rather than re-running.)

The library keeps a small database of everything already explored:
`$LIB/registry.json`. Read it before anything else — read
`references/registry.md` for its schema and rules.

**Identity is the `process` + `industry` pair.** Order Management in chilled dairy and
Order Management in generic pharmaceuticals are different explorations; the same pair
studied twice is the *same* exploration. The company is context, recorded on the
entry, never part of the key. Directory:
`$LIB/<process-slug>__<industry-slug>/`.

| What the registry says | What to do |
|---|---|
| The pair exists **with** the requested language | **Stop and open that file.** No research, no render, no translation. Say when it was generated and which languages it holds. |
| The pair exists, language missing | Skip Phases 2–4. Reuse `research/*.md` and the existing `content.<code>.md`, **translate only**, write the new `content.<code>.md` + `index.<code>.html`, then append the language to the entry. |
| The pair exists, but for a **different company** | Skip Phase 2's industry research — it still holds. Run only `company-researcher`, refresh the company-dependent parts (systems, Challenge narratives, use-case ranking), append the company to `companies`, and bump `updated`. Do not create a second directory. |
| The pair exists and the user brings **new material** | Re-ingest it (Phase 1b), re-reconcile, and regenerate the affected sections. New context is always a reason to refresh — it outranks whatever the existing content was built from. |
| The pair is absent | Run the full flow from Phase 1. |

Only re-run industry research when the user asks to refresh it, or it is older than
about three months and they want it current.

## Phase 1 — Collect inputs

Ask for all three in a single `AskUserQuestion` call (one question each). Never
guess a company. Only skip a question when the user's prompt already stated that
value.

| Field | Options to offer | Notes |
|---|---|---|
| **Process** | the processes already in `$LIB/registry.json` first, then Order to Cash · Purchase to Pay · Inventory Management · Plan to Produce | free text allowed via "Other" |
| **Company** | recent accounts from `~/.atlas/accounts/*.md` if any exist | otherwise ask as free text |
| **Language** | English · Italiano · Deutsch | drives *all* rendered text |

When the registry already holds explorations, list them in the question so the user
can pick one to reopen instead of generating anything.

## Phase 1b — Take the user's own material, if they have any

If the invocation already carried paths — a folder or individual files — take those as the
material and skip the question. Otherwise ask once: *"Do you have any of their own material
— a process handbook, glossary, KPI definitions, a BPMN export, workshop notes? A folder
path, file paths or pasted text all work."* If they say no, continue; never block on it.

If they do supply something, read `references/user-context.md` and follow it. In short:

- **A folder means everything readable inside it, recursively** — list it first, report what
  you found and what you are skipping (binaries, archives, anything unreadable), then ingest.
  A folder that exists but holds nothing readable is worth saying out loud, not passing over.
- **Read every file** (`pdftotext`, `unzip` for DOCX/PPTX/XLSX XML, images read as
  images) — never use a file you have not opened.
- Copy the sources into `<out>/context/` and write `<out>/context/extracted.md`, one
  section per source, as the audit trail.
- **It outranks both research agents.** Precedence: user context → account research →
  industry research. Their terminology, step order, glossary definitions, KPI formulas
  and named systems win outright.
- Pass a **condensed excerpt** to both agents in Phase 3 with the instruction that it is
  authoritative, that they must not contradict it, and that they should research the
  gaps around it and flag anything in it that looks outdated.

## Phase 2 — Resolve the industry (before research)

The industry decides how the process is framed, so establish it **first** and cheaply:

1. If `~/.atlas/accounts/<Company>.md` exists, read its industry field — that is
   authoritative.
2. Otherwise run one `WebSearch` for the company's industry and sub-segment.
3. State the resolved industry to the user in one line and continue. Do not block
   on confirmation unless the company name was genuinely ambiguous (two real
   companies share it).

## Phase 3 — Research, in parallel

Three roles, and only two of them are subagents:

| Role | Who | Does |
|---|---|---|
| **Process research** | `process-enablement:process-researcher` | how this process runs in this industry |
| **Account research** | `process-enablement:company-researcher` | the account — website, news, filings — and what it should change |
| **Industry expert** | `process-enablement:industry-expert` | practitioner-level depth: edge cases, misconceptions, what teams argue about — and later, the agent behind the page's chat |
| **Orchestration** | **you, the main conversation** | reconciles all three, writes the content, renders the HTML, updates the registry |

Dispatch the three researchers in **one message with three Agent calls** so they run
concurrently.

The orchestrator is deliberately not a subagent: it needs the user in the loop for the
checkpoints, and its output is the deliverable rather than a report. It writes the
content, the page and the registry — the three research files belong to the agents that
produced them.


Pass each one its own brief:

- `process-enablement:process-researcher` — pass `process`, the resolved
  `industry`, and `company` for context.
- `process-enablement:company-researcher` — pass `company` and `process`.
- `process-enablement:industry-expert` — pass `process`, `industry` and the context
  excerpt; ask for the depth a newcomer's questions will hit (edge cases, common
  misconceptions, the arguments practitioners have) to enrich the content. **Phrase it as
  a numbered list of topics** so the agent uses ENRICHMENT mode and returns structured
  Markdown; a single question puts it in CHAT mode and you get one JSON note instead of
  the page material you asked for.

All three return structured Markdown.

**Each agent saves its own return; you never re-emit it.** Create
`<out>/research/` first — `<out>` is `$LIB/<process-slug>__<industry-slug>/`, the
pair-keyed directory Phase 0 resolved — then give every agent the absolute path it owns
and tell it to write its findings there verbatim as its final act, and to reply with only
a short digest: the path, the byte count, its section headings, and the three or four
findings that change the content.

| Agent | Writes |
|---|---|
| `process-researcher` | `<out>/research/industry.md` |
| `company-researcher` | `<out>/research/company.md` |
| `industry-expert` | `<out>/research/expert.md` |

These files are the audit trail for every claim on the page, so they must be the agent's
full findings, not a summary — the summarising happens in the digest, not in the file.
Having the agent write directly is what keeps a 40 KB return from crossing into your own
context and being written out a second time; that round trip is both the slowest step in
the run and the one that most often loses a stream. Confirm each file exists with
`wc -c` before Phase 4, and read a file only when you actually need a passage from it.

Do not start rendering until all three have returned. If one fails, re-dispatch that one
alone rather than proceeding on partial input.

## Phase 4 — Reconcile

The orchestrator (you, the main conversation) does Phases 4–6 itself. Do not
delegate them — the agents research; you teach.

Before writing anything, resolve the two research sets into one coherent story:

Apply precedence first: **user-supplied context beats account research beats industry
research.** Where the context settles something — a step name, a definition, a KPI
formula, a system — take it and discard the generic version rather than averaging them.

Then work through the account researcher's `## What this should change` list — it names
which part of the page each finding touches. Then:

- **Systems**: named in the user's material → use it and drop the marker. Otherwise the
  account's actual landscape; otherwise the industry-typical, marked `[typical]`.
- **Terminology**: their words rename the same thing *everywhere* — flow chain, step
  frames, document cards, glossary, quiz. Never render "their term (also known as …)".
- **Deviations**: keep those the company's own pressures make plausible; drop
  industry deviations that contradict its model.
- **Steps**: use the industry's canonical flow, renamed to the company's own
  vocabulary where research revealed it.
- **Financial impact**: only state a figure that came from a source. Otherwise
  describe the damage mechanism in a sentence. Never scale a benchmark to the
  company's revenue and present the result as fact.
- **Flow linkage**: reconcile the two research sets into ONE graph with no orphan
  steps. If the company's own vocabulary renames a step, rename it everywhere.
- **Use cases**: rank by fit to the account's stated strategic priorities.
- **Steps**: an operating-model fact (extra entities, an in-flight ERP migration, a
  channel the generic flow ignores) may justify adding a step or a branch — do it, and
  say in the step's text that it exists because of that fact.

**The pair is the identity; the account is what makes the content specific.** Two
explorations of the same Process + Industry pair studied for different accounts are the
same exploration with different company-shaped detail — which is why new account
information is a reason to refresh an existing pair, not to fork it.

## Phase 5 — Build the content (before any HTML)

**Write the teaching content first, as Markdown, and only then render it.** Mixing
the two produces a page that looks right and teaches nothing.

Read `references/enablement-style.md`. If `Enablements content/` is present, skim the
source decks (images included) — they are the worked examples. The bundle ships without
them, so `enablement-style.md` alone is enough; the PDFs only sharpen it. They are the
worked examples of how to explain a process to someone who has never seen it.

Write `<out>/content.md` **one section at a time**, in the selected language. It runs to
40–60 KB, so a single write loses it to the idle timeout — use the part helper, whose
numbering is the section list below:

```bash
P="$CLAUDE_PLUGIN_ROOT/scripts/pe-parts.sh"
"$P" new "<out>/content.md"
"$P" put "<out>/content.md" 01-purpose      <<'MD'
… that section only …
MD
"$P" put "<out>/content.md" 02-landscape    <<'MD'
…
MD
# … 03-personas 04-objects 05-example 06-flow 07-deviations 08-steps
# … 09-kpis 10-problems 11-objectives 12-terminology 13-quiz
"$P" list     "<out>/content.md"     # what has landed
"$P" assemble "<out>/content.md"     # concatenate in NN order
```

Split the two heaviest sections further — `08a-steps-1-5`, `08b-steps-6-9`, and one part
per problem group if the Challenge narratives are long — rather than letting any one call
approach 8 KB. Assemble only once every part is in; `list` before assembling, and if a
call was lost, re-`put` that part alone. Keep the part set until the page renders clean,
then `drop` it.

The sections, in order:

0. **Provenance is visible.** Anything taken from the user's material carries a
   `from your context` chip; anything still generic keeps `[typical]` / `[unverified]`.
   A reader must see at a glance which parts are the customer's own words.
0. **Everything as full sentences.** Inputs, outputs, KPI definitions, object
   definitions, persona accountabilities and deviation damage are prose a newcomer
   can act on — never bare keywords. `Input: customer order` is a defect;
   "a customer's purchase order, arriving by EDI, portal or email, stating which
   materials they want, in what quantity, to which ship-to location, and by when"
   is the standard. Apply this check to every field before moving on.
1. **Purpose** — one sentence. **Goals** — exactly three, numbered. **Input** and
   **Output** — a full sentence each saying what the thing is, where it comes from
   or goes, and in what state; then why the organisation depends on the process.
2. **Where it sits** — the end-to-end chain this process belongs to, its upstream and
   downstream neighbours, and for each boundary: **what object crosses it**, **what a
   poor handover costs this process**, and **where the boundary actually falls**
   (start and end, each contrasted with what readers wrongly assume). Close with what
   is deliberately not this process's job, and note that each of those can still
   block it.
3. **Personas** — 2–3, first name, role, and a first-person quote in their voice.
4. **Key objects** — 3 main ones, each with a plain "Document that records …"
   definition and an assigned colour; plus a footnote naming the others.
5. **One running example** — invent a single concrete case (order number, customer,
   amount, dates, 2 line items) and **carry it through every step**. Define it once,
   here, and never change a value later.
6. **The overall flow** — the happy path as a linked chain: for every step, what
   precedes it and what follows it. Keep deviations out of this chain.
6b. **Common deviations** — 2–4, each with a name and four parts: what happens, what
   triggers it, how the case comes back, and what it costs. Say which step it leaves
   after and which it rejoins at. These are taught beside the steps, never drawn on the
   flow.
7. **Steps** — 5–9. For each: name, the persona who acts, `Follows` / `Leads to`,
   a 2–3 sentence description of what happens and what changes as a result, a
   worked **example in full sentences** using the one running case, the documents
   that exist after it with this example's field values, and a volume figure only
   if research supplied one.
8. **KPIs** — a paragraph each: what it measures, how it is calculated in words,
   why a bad value hurts, which event starts the clock, the good → late → damaging
   boundaries, the definitional trap where one exists, **and a structured example**
   (see rule 8b).
9. **Improvement opportunities** — each as **Concept → Challenge**, and stop there.
   Concept defines the mechanism neutrally; Challenge is the company's own
   situation from research, **and each one carries a structured example** (rule 8b).
   **Write no Solution stage, no remedy, no vendor capability** — this page
   diagnoses, it does not prescribe.

8b. **Every Process Challenge and every KPI carries a structured example — no
    exceptions.** Not a paragraph: **3–4 lines of `Label: value`**, one per line,
    built from the one running case (same order number, material, amounts, dates),
    with the **last line the effect** in currency, days or percent. A KPI's example
    shows its own arithmetic — standard, actual, variance — so the reader can see
    the number being computed rather than described. Never a figure research did not
    supply: where none exists, name the mechanism and the unit instead of inventing
    one. The prose descriptions stay exactly as they are; the example is added
    beside them, never instead of them.
10. **Business objectives** — which objective each problem and KPI belongs to.
    This grouping paces the Process Challenges screen; it is never rendered as a dense grid.
11. **Terminology** — 8–15 terms, one or two full sentences each: the definition
    *and* why the term comes up in a workshop. **Tag every entry** — terms, systems and
    people alike — `from your context` or `typical`. Nothing on this tab may be
    untagged; it is the wording that gets used in front of the customer.
12. **Ten quiz questions** — one per mechanism worth testing, drawn from across all
    five content screens, each with four options, the correct answer, and a
    one-sentence explanation of why. Test understanding, not recall of labels.

No takeaway summary — the content ends when it is done.

Then re-read it once against three tests, and fix what fails before moving on:
- *Would someone who has never seen this process understand it from this alone?*
- *Is every step linked — can I trace a case from entry to exit with no gap?*
- *Is any input, output, KPI or definition still just a keyword?*

## Phase 6 — Render the HTML

Only now read `references/html-spec.md` **and `references/celonis-ui.md`**. The result is
`<out>/index.html` — one file, no external assets, no CDN — and it is a rendering of
`content.md` that introduces no fact not already there.

**Never write that file whole.** It is ~120 KB, almost all of it CSS, JS and two base64
images that are identical in every exploration and already correct in the mock. A render
only changes the data blocks and a little markup, so copy the mock on disk and splice
those blocks in, each one a small write of its own:

```bash
cp "$CLAUDE_PLUGIN_ROOT/skills/explore/assets/reference-mock.html" "<out>/index.html"
mkdir -p "<out>/.blocks"
# write one small file per data block: steps.js, deviations.js, probs.js, kpis.js,
# people.js, quiz.js, glossary.js, flow.html … then splice them all in one pass
python3 "$CLAUDE_PLUGIN_ROOT/scripts/pe-splice.py" \
  --base "<out>/index.html" --out "<out>/index.html" \
  --const STEPS="<out>/.blocks/steps.js" \
  --const DEVIATIONS="<out>/.blocks/deviations.js" \
  --const PROBS="<out>/.blocks/probs.js" \
  --const KPIS="<out>/.blocks/kpis.js" \
  --const PEOPLE_SRC="<out>/.blocks/people.js" \
  --const QUIZ="<out>/.blocks/quiz.js" \
  --set "CURRENT_ID='<process-slug>__<industry-slug>'" \
  --set "CURRENT_LANG='en'" \
  --check
```

`--const NAME=FILE` replaces the initializer of `const NAME = …;` by matching brackets, so
nested arrays and objects are safe. `--region NAME=FILE` replaces markup between
`<!-- PE:NAME -->` and `<!-- /PE:NAME -->`. `--set NAME=VALUE` stamps a scalar. Every
anchor must resolve exactly once, and with `--check` the file is written only after
`node --check` parses the spliced JS — so a missing anchor or a broken block leaves the
previous file untouched instead of publishing a half-rendered page. Always pass `--check`.

For the handful of small edits the splicer does not cover — a heading, the company label —
use ordinary targeted edits against the copied file. What you must not do is regenerate
the whole document to change a few kilobytes of it.

The same mechanism does the library-wide `REGISTRY` restamp in Phase 6b: one
`--const REGISTRY=<file>` call per `index*.html`, never a rewrite of each page.

Five rules the render must satisfy:
- **It must look like Celonis.** Grey canvas, white bordered panels, underline tabs,
  **blue `#1a40ff` for every interactive element and purple/magenta for the process
  data**, small-caps labels, compact controls — per `references/celonis-ui.md`. Copy
  the tokens from the reference mock; do not invent a palette.
- **It fits the viewport.** The window never scrolls: the shell is a flex column and
  the active tab pane is the scroll container, with the flow chain sticky above it.
- **One thing on screen at a time.** Six tabs, each with a single job: **Overview ·
  Process Step-by-Step · Process Challenges · KPIs · Terminology · Personal Notes** — use those
  exact labels, translated.
- **The header carries the actions**: a clickable globe icon opening a language
  dropdown, then *Quiz* and *Export* — both **solid blue with white text**, since they
  are the page's two primary actions.
- **The company is stated, not selected**: a label reading *Content for specific
  company* with the account's name beside it. Only Process and Industry are dropdowns —
  they switch exploration; the company is what this content was shaped for. Those two buttons live top-right beside the language icon, never at the
  bottom of a content tab. Nothing is pinned above the tabs, nothing
  repeats between them. Where a tab holds several items, it is a list on the left
  and one explanation on the right. The knowledge stays complete — it is paced, not
  cut.
- **No pop-ups, modals or dialogs.** Every explanation sits in the frame that owns
  it; clicking changes what a frame shows, it never opens a layer. Two things sit above
  the page by design and neither is an explanation of content: the **quiz**, which is its
  own screen, and the **guided tour's coach card**, which is non-modal, dismissible, and
  explains the interface rather than the process.
- **Every page ships the guided tour** — sixteen steps walking the reader through all
  screens on first open (including how to switch the chat on, how the language switch
  works, and what the quiz and the two exports actually do), a *Guide* button in the
  header to reopen it, and one
  `localStorage['pe-tour-v1']` flag so it happens once per reader. The steps, their copy
  and the button are **chrome**: identical on every page, derived from nothing in the
  exploration, carried by `pe-sync-template.py`. Neither invent steps nor drop them —
  see `references/html-spec.md`.
- **The whole flow is drawn linked** at the top of the step-by-step tab — every
  step connected, branches and loop-backs labelled with their condition — and stays
  visible while the reader explores individual steps.
- **No Solution stage.** Process Challenges render as Concept and Challenge only.
- **No footer.** No takeaway cards.
- **Personal Notes** files every chat answer as a small piece of enablement — a topic
  heading, then **Explanation / Example**, and nothing else — plus the screen and item it
  was asked from, persisted in `localStorage` under `'pe-notes-' + CURRENT_ID`. Every
  exploration shares the `file://` origin, so a hardcoded key leaks notes between
  explorations; `CURRENT_ID` is declared at the top of the script and both persisted keys
  derive from it. The chat says so in its opening message
  and confirms each filing in the log. Both exports carry the same three fields, and the
  count appears in the Export menu's heading — never as a badge on the button.
- **The quiz is a full-screen overlay frame**, opened from the header's *Quiz*
  button: dimmed backdrop, one centred card, ten questions one at a time with letter
  badges and locked answers, then a score ring and a full review. Never toggle
  `hidden` on `main` or the tabs to achieve this — their `display` rules override
  `hidden` and the quiz ends up below the fold.
- **Export offers two formats** from one header button: **PDF** (hidden print-only
  linear document + `window.print()`, for a person) and **Markdown `.md`** (YAML front
  matter + bold-labelled full sentences, downloaded via a Blob, for an agent).
- **Personal notes are woven into the exported knowledge**, not appended: each note is
  filed into the section its anchor names — the step, problem or KPI it was asked from.
  Only unmatchable notes fall through to a short *Further notes* section.

### One file per language, generated once

The first language renders as `index.html`; every later one as
`index.<code>.html` (`index.it.html`, `index.de.html`), beside its own
`content.<code>.md`. Nothing is translated in the browser — the language switcher
just loads the sibling file.

In every file, stamp the two constants the switcher reads:

- `CURRENT_LANG` — this file's language code;
- `AVAILABLE` — the codes actually present in the directory.

When you add a language, **update `AVAILABLE` in every existing `index*.html` too**, so each
file offers the full set even offline. When the bridge is running, the menu prefers the live
language list from `GET /health`, so a language generated from inside the page appears
immediately without restamping.

A reader can also generate a language themselves: a row marked *translate* POSTs to the
bridge's `/translate`, which translates the page's extracted strings as a dictionary,
substitutes them mechanically, gates the result on `node --check` **and on a 90% coverage
measurement**, saves the file, records it in `$LIB/registry.json` and restamps the `REGISTRY`
snapshot of every page in every exploration of the library. It runs **in the background** — the row shows `translating… 1:35`
with a hover `✕ stop`, and the page stays fully usable. A language is never offered as *ready*
until the whole page is translated; an unfinished one shows its percentage and can be
retranslated. Nothing is translated in the browser, and the CLI never rewrites the page. A language not in `AVAILABLE` shows as *not
generated* and the switcher refuses to load it, rather than 404ing.

Translate **all** user-visible chrome too — headings, tab labels, table headers,
the chat placeholder, and the two header buttons. Keep proper nouns (system names,
company name, incoterms, "OTIF", "DSO") untranslated.

Then open it: `open "<out>/index.html"`.

## Phase 6b — Record it in the library

Merge an entry into `$LIB/registry.json` — never overwrite the file:

- key it `<process-slug>__<industry-slug>`, with `process`, `industry`, `companies`,
  `path`, `languages[]`, the counts (`steps`, `problems`, `kpis`, `terms`),
  `created` / `updated`, the `research` paths, and `context[]` — the source files the
  user supplied, so a later run knows the pair was grounded in their own material;
- keep the array sorted by `updated`, newest first;
- drop any entry whose directory no longer exists;
- **append only what exists.** Write the entry after the file is written, and add a
  language only once its `index.<code>.html` is on disk. An option in a header dropdown
  with no file behind it lands the reader on `ERR_FILE_NOT_FOUND`.

Then **stamp the registry snapshot into every page**. A `file://` page cannot fetch
local JSON, so each `index*.html` carries a `REGISTRY` constant and its own
`CURRENT_ID`. After changing the registry, restamp *all* existing pages in *all*
exploration directories — otherwise an older page offers a library missing the newest
entries, and its dropdown navigates nowhere or to a language file that is not there.
Switching exploration keeps the reader's language when the target has it, defaults to
English when it does not, and only falls back to the target's first language when it has
no English.

## Phase 6c — Start the chat bridge yourself

Do not leave this to the reader. Someone opening the page has a Claude session on their
machine by definition — they just got the page from one — so the chat should already work
when the page opens.

Right before opening `index.html`, start the bridge in the background from the
exploration's directory:

```bash
nohup python3 "$CLAUDE_PLUGIN_ROOT/scripts/chat-bridge.py" \
      --dir "<out>" --port 8787 > "<out>/.chat-bridge.log" 2>&1 &
sleep 1 && curl -s http://127.0.0.1:8787/health      # confirm before you report success
```

- If port 8787 is taken by another exploration's bridge, use 8788 or 8789 — the page
  probes all three and prefers the one whose `--dir` matches its own folder.
- If `/health` returns `"claude": false`, say so: the page will show *no Claude* and the
  chat cannot work until a `claude` CLI is on `PATH`.
- Mention the **refresh icon beside the chat's status dot** as the way to bring the chat
  back later — one click re-probes and, if nothing is running, starts a bridge for this
  exploration through the launcher agent. `pe-chat <dir>` is the terminal equivalent, and
  now only a footnote to a footnote: it should be running already, and the icon covers the
  reader who comes back tomorrow.
- Run `bash "$CLAUDE_PLUGIN_ROOT/scripts/setup.sh" --quiet` as usual: it installs the
  launcher agent when it is missing, which is what makes that icon able to start anything.
  A `LAUNCHER	skipped` or a failure line is worth one sentence in the report — the page
  still works, the icon just falls back to naming the command.

The page needs no reload if the bridge starts late: it probes on load, keeps polling
every four seconds while it is down, and re-checks on window focus.

**The bridge stops when the page does.** It is a local process serving one open tab: the
page heartbeats while it is open and beacons `/bye` when it closes, and the bridge then
exits and kills every `claude` subprocess it started — so a closed tab leaves nothing
running. A closed browser that never got to say goodbye is caught by the missing
heartbeat instead. The exploration itself is untouched: `content.md`, `research/`,
`context/`, finished translations, `registry.json` and the reader's notes all persist —
only a translation caught mid-render is discarded. Tell the reader the bridge closes with
the tab, and that **the refresh icon brings it back** — no terminal, no reload. Pass
`--keep-alive` only if something genuinely needs the bridge to outlive the page.

## Phase 7 — Report

Tell the user, briefly:
- the resolved industry and where it came from;
- how many steps, deviations, terms and use cases the page holds;
- anything marked `[unverified]`, `[inferred]` or `[typical]` that they should
  sanity-check before showing a customer;
- the path to the language file (`index.html` or `index.<code>.html`), its
  `content.<code>.md`, the two research files, and `context/extracted.md` if material
  was supplied;
- which parts came from their material versus research, and anything in their material
  that looked outdated or self-contradictory;
- which languages the directory now holds, and that revisiting one is free;
- how many explorations the project now holds, and that the header's Process and
  Industry dropdowns switch between them.
- that the page reads as six calm screens, and where a reader should start;
- that the chat is live (with the bridge's port), or exactly why it is not;
- that the chat header carries the refresh control (`#chatRfsh`) — every rendered page
  must have it, and `scripts/pe-patch-refresh.py <file>` retrofits it into a page that
  was rendered before it existed.

## Rules

- **No invented figures, names, or system versions.** Ever. An unsourced euro
  amount in a customer-facing page is a liability — describe the mechanism instead.
- **No solutions and no product pitch.** Diagnosis only, end to end.
- **No pop-ups.** If a fact matters, it is in the frame.
- **No keyword-only fields.** Inputs, outputs, KPIs and definitions are sentences.
- **The user's material wins.** Never override their terminology or step order with a
  researched generic, and never present a blend of the two as if it were theirs.
- **Never translate the same language twice.** Check Phase 0 first; a language that
  exists is opened, not regenerated.
- **One exploration per Process + Industry pair.** Never create a second directory for
  a pair that exists — extend it. The company is context, not identity.
- **The registry is the source of truth**, and every page's `REGISTRY` snapshot must be
  restamped whenever it changes.
- **Never offer what does not exist.** Dropdowns list only generated pairs and only
  generated languages; with a single exploration, both selects are disabled rather than
  offering a dead choice.
- The HTML must open correctly from `file://` with no network.
- One page per run; never overwrite a previous run's output directory — suffix
  `-2`, `-3` if it exists.
- The visual design is fixed by `references/html-spec.md` and
  `assets/reference-mock.html`; content varies, layout does not.

## Files

- `references/enablement-style.md` — **how to teach a process**, distilled from the
  Celonis Process Enablement decks. Read before writing content.
- `references/html-spec.md` — required page structure and component behaviour.
- `references/celonis-ui.md` — the Celonis look: tokens, shell, type, process-explorer
  conventions, tables, focus states. Read before writing any CSS.
- `references/ui-notes.md` — the original handwritten UI sketch and its transcript.
- `assets/reference-mock.html` — working reference implementation. Copy it on disk and
  splice the data blocks in; its CSS, JS and both base64 images are already correct.
- `../../scripts/pe-parts.sh` — writes `content.md` as small, individually retryable
  parts and concatenates them in order.
- `../../scripts/pe-splice.py` — replaces named JS data blocks and marked markup regions
  inside a copy of the mock, gated on `node --check`, so a page is never written half
  rendered.
- `../../Enablements content/*.pdf` — the source enablement decks (OM, IM, Procurement),
  when present. The gold standard for tone, structure and visual convention; not shipped
  in the shared bundle.
