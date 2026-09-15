# Process Enablement

> Francesco's plugin, preserved here with version history and a minimal adapter for
> Claude Code and OpenAI Codex.

## In 30 seconds

Give it a **business process**, a **company** and a **language**. It researches the
process and account, then creates a self-contained interactive HTML primer with the
process flow, common challenges, KPIs, terminology, a quiz, notes and export options.

It is useful for preparing discovery workshops, learning an unfamiliar customer
process, and onboarding Value Engineers or Solution Consultants before a meeting.

### Repository scope

| Ref | What it contains |
|---|---|
| [`v0.0.1`](https://github.com/mbravomartinez/process-enablement-francesco/releases/tag/v0.0.1) | The first version received, plus the portability and security adjustments made during its initial review |
| [`v0.2.1`](https://github.com/mbravomartinez/process-enablement-francesco/releases/tag/v0.2.1) | Francesco's newer, more stable version, plus the minimal Codex manifest |
| [`main`](https://github.com/mbravomartinez/process-enablement-francesco) | The current version: `v0.2.1` |

See the [full comparison between v0.0.1 and v0.2.1](https://github.com/mbravomartinez/process-enablement-francesco/compare/v0.0.1...v0.2.1).

### Runtime compatibility

- **Claude Code:** native plugin commands such as `/process-enablement:start`.
- **OpenAI Codex:** the same `explore` skill is available through the included
  `.codex-plugin/plugin.json`; invoke it in natural language, for example:
  `Use process-enablement to explore Order Management at Barilla in Spanish.`
- **Important:** the generated page itself works in either case, but its optional
  local interactive chat currently calls the `claude` CLI.

The plugin does not include customer data, credentials or generated explorations.
Those stay locally in `~/.process-enablement/output`.

---

Turn three inputs — **a process, a company, a language** — into one self-contained HTML
page that teaches how that process actually runs, to someone who has never seen it.
Grounded in parallel research, styled like the Celonis app, and answerable: the page has
a chat wired to the Claude session on your own machine.

Built for Celonis Value Engineers and SCs preparing for a discovery workshop, and for
onboarding anyone onto an unfamiliar process.

---

## What you get

One HTML file per exploration, offline-capable, six calm screens:

| Screen | What it holds |
|---|---|
| **Overview** | Purpose, three goals, input → output as full sentences, why the organisation depends on it, and where the process sits — with the **handovers** to the neighbouring processes and what a poor handover costs |
| **Process Step-by-Step** | The happy path as a linked chain, then one step at a time: the acting persona, what happens, the running example at that point, and the documents that now exist. Below the steps, **Common deviations** explained in four parts |
| **Process Challenges** | Grouped by the business objective they put at risk. One at a time: **Concept** (the mechanism) → **Challenge** (how it plays out here), with root causes and how the damage happens |
| **KPIs** | One measure at a time: what it measures, why a bad value hurts, what starts the clock, and **where it misleads** — on a timeline, never a formula |
| **Terminology** | Terms, systems and people. **Every entry tagged** `from your context` or `typical`, so you always know whose words you are about to use |
| **Personal Notes** | Every chat answer, filed as enablement — *a short explanation · a worked example* — anchored to the screen and step you were on |

Plus: a **Quiz** (10 questions, own screen, score ring and full review) and **Export** to
**PDF** or **Markdown**, with your notes woven into the section they belong to rather
than appended.

**First time you open an exploration, it walks you through itself.** Sixteen steps, switching
screens as they go — what each tab holds, how to select a phrase and ask about it, how to switch
the chat on and read the status dot, how a language is generated and kept — that step opens the
language menu while it explains it — how the chat files notes, what the provenance chips mean,
what the quiz does and what each export is for.

The language menu carries **its own Claude refresh**, next to the word *Language*: translation
needs a session, and this is where you find that out, so the control that starts one is here too
rather than across the page. It advances
only when you click *Next*, never on a timer, and the card never blocks the page it is
explaining. It runs **once per reader** (not once per exploration), and the **Guide** button in
the header reopens it whenever you want.

---

## Install

```bash
# in Claude Code
/plugin
#   → Add plugin from local directory → point at this folder
```

Or, if a colleague sent you `process-enablement-0.2.1.zip`:

```bash
unzip process-enablement-0.2.1.zip -d ~/claude-plugins/
claude plugin validate ~/claude-plugins/process-enablement    # optional sanity check
# then /plugin → Add plugin from local directory → ~/claude-plugins/process-enablement
```

## First run

```
/process-enablement:setup
```

Idempotent, and worth running once after installing: it creates your exploration library,
writes an empty registry into it, restores executable bits the zip may have lost, and tells
you what is missing. `/process-enablement:start` and `/process-enablement:library` run the
same check silently, so setup is never something you can forget — the command exists so you
can see the report and re-run it when something looks broken.

| Needed | For what | If absent |
|---|---|---|
| **Python 3** | the chat bridge and the library index; stdlib only | the pipeline cannot run — `brew install python` |
| **Claude Code CLI** (`claude` on `PATH`) | the chat inside a generated page | pages still generate and read fine, chat stays dark |
| `pdftotext` | ingesting scanned PDFs | only needed for that — `brew install poppler` |
| `node` | syntax-checking a generated page's JS | optional |

**Your library lives at `~/.process-enablement/output`** — one directory per
process + industry pair, plus `registry.json`. It is deliberately outside the plugin, so
updating or reinstalling the plugin never touches your explorations. Set `PE_HOME` to move
it (e.g. `PE_HOME=~/Drive/pe`). A fresh install starts empty: you never inherit anyone
else's explorations, and yours are never in the zip you send on.

### Starting over

Re-running `/process-enablement:setup` never deletes anything — it only fills in what is
missing. A wipe is a separate, explicit request:

```
/process-enablement:setup reset
```

It first shows how many explorations would be lost and asks you to confirm, then either
moves the library aside to `~/.process-enablement/output.backup-<timestamp>` (the default —
move it back to restore) or deletes it outright if you choose that. `--status` is the
read-only version: what's in the library, what's missing, nothing changed.

## Run it

```
/process-enablement:start                              # it will ask what you need
/process-enablement:start Order Management at Barilla
/process-enablement:start Order Management at Barilla ~/Drive/Barilla/OM-handbook
/process-enablement:start Purchase to Pay at Nestlé ~/notes/p2p-workshop.pdf
```

Anything path-shaped in the arguments is treated as **additional context**, not as part of
the process or company name: point it at a folder — or an individual file — anywhere on
disk where you keep the customer's own, more detailed process material, and the run reads
it before it researches anything. A folder means everything readable inside it,
recursively. See *Their own material* below for what that outranks.

That command is the front door: it hands straight to the plugin's **`explore`** skill,
which owns the pipeline. You can also invoke the skill directly
(`/process-enablement:explore`), or just describe what you want — it self-invokes on
requests like *"explore Purchase to Pay at Nestlé"* or *"prep me on how Order Management
runs at Bayer"*.

### Plugin, skill, command — which is which

| | What it is | Here |
|---|---|---|
| **Plugin** | the installable, shareable package — manifest, agents, skills, scripts | **`process-enablement`** — what you install and send to colleagues |
| **Skill** | the instructions Claude loads to do the work | `explore` — the pipeline itself, in `skills/explore/SKILL.md` |
| **Command** | a slash-command front door | `/process-enablement:start` — a thin wrapper that runs the skill |
| **Agents** | subagents the skill dispatches | the three researchers |

So: it is a **plugin**, and the skill is its engine. You invoke the plugin; the skill runs
behind it.

You will be asked for four things:

1. **Process** — already-explored processes first, then the usual suspects
2. **Company** — the account whose reality shapes the content
3. **Language** — English · Italiano · Deutsch · Français
4. **Their own material**, optionally — a process handbook, glossary, KPI definitions, a
   BPMN export, workshop notes, an SAP configuration extract. A folder path, individual
   file paths, or pasted text; give it on the `/start` line or when asked.
   **This outranks all research.**

---

## How it works

### Three roles

| Role | Who | Does |
|---|---|---|
| **Process research** | `agents/process-researcher.md` | how the process runs in this industry — the linked flow, deviations, KPIs, terminology |
| **Account research** | `agents/company-researcher.md` | the account's website, newsroom, filings, coverage → priorities, systems, pressures, and **what each finding should change** |
| **Industry expert** | `agents/industry-expert.md` | two modes: **enrichment** (structured Markdown, practitioner depth while generating) and **chat** (one four-field JSON note, live in the page) |
| **Orchestration** | the skill, in your main conversation | reconciles all three, writes the content, renders the HTML, updates the library |

The orchestrator is deliberately not a subagent: it writes every file, it needs you at
the checkpoints, and its output is the deliverable rather than a report.

### The flow

0. **Check the library** — `output/registry.json`. An exploration already there in the
   requested language is opened, not regenerated.
1. **Ask** for process, company, language and any of their own material.
2. **Ingest their material** — PDF, DOCX, PPTX, XLSX, MD, images — into
   `output/<pair>/context/` with an `extracted.md` audit trail.
3. **Resolve the industry** (from `~/.atlas/accounts/` if present, else one search).
4. **Research in parallel** — three agents, one message.
5. **Reconcile** — their material beats account research beats industry research. Never a
   blend presented as theirs.
6. **Write the content first** (`content.md`), then render the HTML from it.
7. **Start the chat bridge**, open the page, and report what needs sanity-checking.

### Source of precedence

| Rank | Source | Wins on |
|---|---|---|
| 1 | The customer's own material | terminology, step names and order, definitions, KPI formulas, named systems |
| 2 | Account research | strategic priorities, pressures, Challenge narratives |
| 3 | Industry research | everything the first two do not cover |

Everything taken from their material is chipped **`from your context`** on the page;
anything still generic keeps **`typical`**. Chips never get removed to make a page look
more authoritative.

---

## The library

One exploration per **Process + Industry pair** — Order Management in chilled dairy and
Order Management in generic pharmaceuticals are genuinely different explorations. The
**company is context, not identity**: it is recorded on the entry, and a second account
studied against the same pair extends that exploration rather than forking it.

```
output/
├── registry.json                                  the library index
└── order-management__consumer-goods-confectionery/
    ├── index.html            index.it.html        one file per language
    ├── content.md            content.it.md        the teaching content, rendered from
    ├── research/industry.md  research/company.md   the audit trail
    └── context/extracted.md                        their material, if supplied
```

The header's **Process** and **Industry** dropdowns switch between explorations; the
**globe** switches language. Both list only what exists, so a selection can never 404.
Languages are generated once and reused — revisiting one costs nothing.

**Your own notes switch language too.** A note is written in the language the page was in
when you asked, and that text is never overwritten — every other language is a translation
kept alongside it, fetched once and then read back. Ask a question on the Italian page and
the answer arrives in Italian, ready to be filed.

---

## The chat

The page's chat is answered by the **`claude` CLI on your own machine**. A `file://` page
cannot start a process, but it can POST to localhost, so the plugin ships a small bridge:

```
pe-chat output/order-management__consumer-goods-confectionery
# or: python3 scripts/chat-bridge.py --dir <that folder> --port 8787
```

**The skill starts it for you** when it opens a page, so the chat is live from the first
question. The bridge (127.0.0.1 only) runs the `industry-expert` agent against that
exploration's own `content.md`, `research/` and `context/`, and returns *a short explanation
· a worked example* — rendered in the chat and filed straight into Personal Notes.

**It closes when you close the tab.** The bridge belongs to the page: while a tab is open
it heartbeats, and on close the page beacons a goodbye and the bridge exits, taking every
`claude` subprocess it started with it — no stray port, no orphaned process, nothing to
clean up by hand. Close the browser outright and the missing heartbeat does the same job
a couple of minutes later — the window is deliberately wider than a browser's throttling of a
background tab, so a bridge is never reaped out from under a reader who switched tabs while
waiting for an answer. An answer or a translation already running holds it open regardless. Your work is on disk and stays there: `content.md`, `research/`,
`context/`, any finished translation, the registry and your Personal Notes all survive. A
translation you had already started is the one thing that outlives the tab on purpose — the
bridge finishes it, writes the language beside the page and *then* exits; one stopped part
way is kept as a partial, so picking *finish* in the language menu carries on from the
percentage it reached instead of starting over. Reopen the page and `pe-chat <dir>` starts a
fresh bridge. If you want one to outlive its page, run it with `--keep-alive`.

### Ask before Claude is up

A page opens faster than a Claude session starts, and the first thing you do with a page is
usually read it and select something. So **an ask that arrives before the session does is
queued, not refused** — a typed question, a selected phrase, or a refinement on a note.
It appears in the chat as what it is — your question, and a line
saying it is waiting — with a *Drop* control if you change your mind. The moment a session
answers, whether you clicked the refresh control by the status dot or one simply came up,
everything waiting is asked in the order you asked it, oldest first, and each answer is
filed under the section and step you were on when you asked — not wherever you have read to
by then. A queued selection keeps its anchor, so the phrase still highlights when the answer
lands.

A queued refinement is added to the note it came from when it finally lands, not filed as a
second note — and if you deleted that note while it waited, the chat says so instead.

The queue is stored per exploration, so it survives the reload you would otherwise do to
make the chat notice you: reopen the page and anything still unanswered is there, waiting.
The same applies to an ask that was live when the session died — it goes back in the queue
rather than disappearing with the connection.

### Refine a note

A note that is close but not quite has a **refine button next to its delete icon**, and
**every block of the note has one of its own** — the explanation, *why it matters*, the
example, and each follow-up already filed. Click the one on the block you mean and the expert
is told exactly which part to do better, and is shown that part's current wording, so it
improves that and leaves the rest of the note alone. You can still write what bothers you in
the field; you just no longer have to spend it saying *the example, not the explanation*. The
answer is added to the note as a follow-up — labelled with what you asked and which part it
was about, kept alongside the original rather than replacing it. The button on the note header
still means the note as a whole.

### Select a phrase and ask about it

Select a phrase and choose *Explain* or *Generate example* — then **say what you actually
want cleared up**. A phrase or a whole paragraph: selecting several sentences works too, up
to about 1500 characters, and it behaves exactly like a phrase — every word reaches the expert,
and the passage is highlighted on the page with the same jump-to-note control, even where it
runs across several paragraphs. Only the note's heading is shortened, since a paragraph makes an
unusable title. The bar turns into a text field: type the part that lost you (*"why does
it stop the invoice and not the shipment?"*), press Enter, and the expert answers that
rather than the phrase in general. Leave it empty and you get the plain explanation.

Anywhere in the content — the Overview, a step, a challenge, a KPI, the terminology — you
can **select a phrase with the mouse** and choose *Explain* or *Generate example*. The
answer lands in the chat and is filed as a Personal Note, and the phrase stays
**highlighted** in yellow with a small `↗` that jumps to the note it produced.

The highlights are not a separate thing you have to manage: they are simply the notes that
came from a selection. Delete the note and the highlight goes with it. Ask about a phrase
you have already asked about and it offers only the mode you are missing — at most an
explanation and an example per phrase, and once you have both, the bar offers the way back
to them instead. A note asked directly in the chat has no highlight, because there is
nothing on the page for it to point at.

On a translated page a highlight reappears only when the phrase can be located
unambiguously from the note's translated topic; when it cannot, you get the note without
the highlight rather than a highlight on the wrong words.

### One note per concept

Ask about three things and you get **three notes**, not one note about three things — each
with its own heading, its own explanation, and its own worked example using the
page's running case. They file into Personal Notes separately, so you can find one later
without re-reading the other two. Ask about one thing and you get one note.

### The refresh icon — you never have to open a terminal

Beside the status dot is a **refresh control**. Click it and it looks for a Claude session
right away instead of waiting out the poll; if there is none, it **starts one for this
exploration** and reports back when the chat is live — typically under a second.

It can do that because `setup.sh` installs one small login agent, `pe-launchd.py`, on
`127.0.0.1:8790`. The page cannot start a process; the agent can, and starting bridges is
the only thing it does. It is deliberately narrow: it takes an exploration's **folder
name**, resolves it inside your library, and refuses anything that is not a folder there
with a rendered page in it — so a page cannot talk it into running over anything else. It
reuses a bridge that already covers the exploration rather than starting a second, and it
never supervises the ones it starts, so a bridge still dies with its own tab.

```
setup.sh                        installs / repairs it (idempotent, run any time)
setup.sh --status               is it running?
setup.sh --no-launcher          skip it — then start bridges with pe-chat yourself
setup.sh --uninstall-launcher   remove it
pe-launcher                     run it in the foreground instead (non-macOS, debugging)
```

The agent is optional. Without it nothing answers on 8790, the refresh icon still
re-probes, and it tells you the `pe-chat` command to run — an install with no launcher is
a normal setup, not a broken one.

The header dot shows the state: **green** with the CLI version when ready, *connecting…*
while nothing answers (it re-probes ports 8787–8789 every four seconds and on window
focus, so a late-started bridge just begins working), and **no Claude** when a bridge is
up but there is no `claude` on `PATH` — in which case the chat says so rather than
inventing an answer. Every other part of the page works without it.

Answers take 20–60 seconds; the chat shows an elapsed counter rather than hanging
silently.

---

## Sharing it with colleagues

**Your explorations stay yours.** `output/` — every generated page, your notes, your
registry — is local and git-ignored, and the bundler excludes it.

```bash
./scripts/bundle.sh                 # → dist/process-enablement-0.2.1.zip
./scripts/bundle.sh --with-decks    # also ships the Enablements PDFs (+~10 MB)
```

The zip contains the manifest, the three agents, the skill and its references, the
scripts and `bin/`, the README, and an **empty** `output/registry.json`. It excludes
`output/`, `dist/`, logs and `.git`.

Three ways to hand it over, in ascending order of how many people it serves:

1. **Send the zip** — Slack or Drive. They unzip it and add it via `/plugin` → *Add plugin
   from local directory*. Fine for two or three colleagues.
2. **A git repo** — push this folder (the `.gitignore` already keeps your sessions out).
   Colleagues clone and add the local directory, then `git pull` for updates.
3. **A marketplace**, if the team wants one command to install and a version they can
   track: add a `.claude-plugin/marketplace.json` at the repo root listing this plugin,
   and colleagues run `/plugin marketplace add <org>/<repo>` then `/plugin install
   process-exploration`. Best for a whole team.

### What a colleague needs

Nothing to configure by hand — they install it and run `/process-enablement:setup`, which
creates their own empty library and names anything missing (see **First run** above for the
dependency table). No API keys, no server, no network calls from the page itself.

They start empty by construction: the library lives outside the plugin, and `bundle.sh`
ships an empty registry, refuses to include `output/`, logs or `__pycache__`, and aborts if
any local path is found in the staged files.

---

## Layout

```
.claude-plugin/plugin.json          manifest — the plugin is "process-enablement"
commands/start.md                   /process-enablement:start — the front door
agents/
  process-researcher.md             how the process runs in this industry
  company-researcher.md             the account as context
  industry-expert.md                practitioner depth + the chat's brain
skills/explore/
  SKILL.md                          the "explore" skill — the flow, phase by phase
  references/
    enablement-style.md             how to teach a process (from the Celonis decks)
    html-spec.md                    required page structure and behaviour
    celonis-ui.md                   the Celonis look — tokens, shell, conventions
    user-context.md                 their own material — precedence and use
    registry.md                     the library's schema and rules
    ui-notes.md                     the original handwritten sketch
  assets/
    reference-mock.html             working reference implementation — open it
    celonis-logo.png  favicon.png
scripts/
  chat-bridge.py                    the local Claude bridge
  pe-launchd.py                     login agent — starts a bridge on the page's request
  pe-sync-template.py               push the template's chrome to every exploration
  pe-patch-refresh.py               retrofit the refresh control onto a rendered page
  bundle.sh                         build a shareable zip
bin/pe-chat                         start the bridge for one exploration
bin/pe-launcher                     run the launcher agent by hand
notes/                              the reMarkable sketch this began as
output/                             LOCAL ONLY — your explorations and library
```

Want to see the output before generating anything? Open
`skills/explore/assets/reference-mock.html`.

---

## Non-negotiables

These are enforced in the skill and the agent prompts, because each one is a way a
plausible-looking page can mislead a customer:

- **No invented figures, names, or system versions.** Unsourced impact is described as a
  mechanism, never as a number.
- **No solutions and no product pitch.** The page diagnoses. Process Challenges stop at Concept →
  Challenge.
- **Full sentences, not keywords.** Inputs, outputs, KPI definitions and terminology are
  prose a newcomer can act on.
- **Provenance stays visible.** `from your context` · `typical` · `[unverified]` chips are
  never removed to tidy a page up.
- **Their words win.** Never override the customer's terminology or step order with a
  researched generic.
- **Never offer what does not exist.** Dropdowns list only generated pairs and languages.
- **The HTML works offline** from `file://` — no CDN, no external fonts, no fetch beyond
  the local chat bridge.

## Changing the page — it must reach every exploration

**Any change to the page's shared chrome — the chat, the bridge probe, the refresh
control, the status dot — is edited in `skills/explore/assets/reference-mock.html` and
then pushed to every exploration you already have.** Never hand-edit a stored page: the
next change would have to find them all again, and they would drift apart.

```
python3 scripts/pe-sync-template.py            # push the template's chrome to the library
python3 scripts/pe-sync-template.py --check    # report drift, change nothing
```

`setup.sh` reports drift on every run, so this cannot quietly stop being true.

What it does **not** do is re-render your old explorations from the template — that would
destroy them. A page is ~99% template by line count, but each one also carries its own
Overview prose, its own document-card renderers and its own CSS, all derived from research
and your material. So a page is two layers: the **chrome**, owned by the template and
replaced on sync, and the **exploration**, which is never touched. The tool is gated by
`node --check` and keeps the previous versions in a stamped backup, so a bad template
cannot take the library with it.

One caveat it reports itself: a translated `index.<lang>.html` gets English chrome labels
back until you re-translate it. Stale code is a broken control; an English label is
cosmetic.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Chat says *connecting…* | no bridge running (a closed tab stops it by design) | click the **refresh icon** by the dot — or `pe-chat <exploration-dir>` |
| Refresh says *no launcher agent* | the login agent is not installed | run `setup.sh` once, then click refresh again |
| Refresh spins, then *did not answer in time* | the bridge started but stalled | read `.chat-bridge.log` in the exploration's folder |
| A page behaves differently from a newer one | its chrome is behind the template | `python3 scripts/pe-sync-template.py` |
| Chat says *no Claude* | bridge up, no CLI on `PATH` | install Claude Code, then `setup.sh` (the agent captures your `PATH`) |
| Language greyed out | that language was never generated | ask Claude for it — it translates the existing content once |
| Notes still in the old language | the bridge was down when you switched | it translates them as soon as the chat says *Claude …* — no reload needed |
| Dropdown has one disabled option | only one exploration so far | ask for another Process + Industry pair |
| `ERR_FILE_NOT_FOUND` after switching | a registry entry outlived its folder | remove the entry and restamp the pages |

## Version

0.2.1 — MIT. Plugin: `process-enablement`. Skill: `explore`. Built from a reMarkable sketch (`notes/`), which is still the design intent.
