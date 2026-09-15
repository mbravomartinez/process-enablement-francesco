# Process Enablement — a Claude Code plugin

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
| **Personal Notes** | Every chat answer, filed as enablement — *what it is · why it matters · an example* — anchored to the screen and step you were on |

Plus: a **Quiz** (10 questions, own screen, score ring and full review) and **Export** to
**PDF** or **Markdown**, with your notes woven into the section they belong to rather
than appended.

---

## Install

```bash
# in Claude Code
/plugin
#   → Add plugin from local directory → point at this folder
```

Or, if a colleague sent you `process-enablement-0.0.1.zip`:

```bash
unzip process-enablement-0.0.1.zip -d ~/claude-plugins/
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
exploration's own `content.md`, `research/` and `context/`, and returns *what it is · why
it matters · an example* — rendered in the chat and filed straight into Personal Notes.

**It closes when you close the tab.** The bridge belongs to the page: while a tab is open
it heartbeats, and on close the page beacons a goodbye and the bridge exits, taking every
`claude` subprocess it started with it — no stray port, no orphaned process, nothing to
clean up by hand. Close the browser outright and the missing heartbeat does the same job
about a minute later. Your work is on disk and stays there: `content.md`, `research/`,
`context/`, any finished translation, the registry and your Personal Notes all survive —
the only thing discarded is a translation that was still rendering, because half a page is
not worth keeping. Reopen the page and `pe-chat <dir>` starts a fresh bridge. If you want
one to outlive its page, run it with `--keep-alive`.

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
./scripts/bundle.sh                 # → dist/process-enablement-0.0.1.zip
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
  bundle.sh                         build a shareable zip
bin/pe-chat                         start the bridge for one exploration
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

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Chat says *connecting…* | no bridge running (a closed tab stops it by design) | `pe-chat <exploration-dir>` — the page reconnects on its own |
| Chat says *no Claude* | bridge up, no CLI on `PATH` | install Claude Code, restart the bridge |
| Language greyed out | that language was never generated | ask Claude for it — it translates the existing content once |
| Notes still in the old language | the bridge was down when you switched | it translates them as soon as the chat says *Claude …* — no reload needed |
| Dropdown has one disabled option | only one exploration so far | ask for another Process + Industry pair |
| `ERR_FILE_NOT_FOUND` after switching | a registry entry outlived its folder | remove the entry and restamp the pages |

## Version

0.0.1 — MIT. Plugin: `process-enablement`. Skill: `explore`. Built from a reMarkable sketch (`notes/`), which is still the design intent.
