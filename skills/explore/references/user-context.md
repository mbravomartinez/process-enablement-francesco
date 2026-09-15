# Context supplied by the user

A run can be given the customer's own material — a folder anywhere on disk, individual
files, or pasted text; on the `/start` line or when asked in Phase 1b. When it is,
that material is **the most authoritative source in the run**, ahead of both research
agents, because it is the organisation describing itself rather than anyone inferring
from outside.

Typical material: a process handbook or SOP, a BPMN or Visio export, a glossary or
data dictionary, a KPI definition document, an SAP configuration extract, a training
deck, a discovery-workshop transcript, a list of known pain points, an org chart.

## Precedence — the whole point

| Rank | Source | Wins on |
|---|---|---|
| 1 | **User-supplied context** | terminology, step names and order, glossary definitions, KPI formulas, systems in use, known deviations |
| 2 | **Account research** | strategic priorities, pressures, public systems facts, Challenge narratives |
| 3 | **Industry research** | everything the first two do not cover — the generic mechanics, typical deviations, benchmark framing |

Where the context and research disagree, **the context is right and the research is
stale or generic** — with one exception: if the context contradicts itself, or is
clearly out of date (a superseded ERP, a renamed entity), say so in the report rather
than silently choosing.

Never *dilute* the context into an average of the two. If their handbook calls the step
"Auftragsfreigabe", the page says Auftragsfreigabe — not "Order Release (also known
as…)".

## Ingesting it

Given a **folder**, walk it recursively and ingest every readable file in it — the folder
is the unit the user thinks in, so never pick a favourite file out of it. List what you
found and what you are skipping before you start, so an unreadable handbook is visible
rather than quietly absent from the page.

Read every file before using it. Practical tools, all local:

| Format | How |
|---|---|
| PDF | `pdftotext -layout file.pdf -` ; for scanned pages, read the pages as images |
| DOCX | `unzip -p file.docx word/document.xml` then strip tags, or `textutil -convert txt` |
| PPTX | `unzip -p file.pptx 'ppt/slides/slide*.xml'` and strip tags |
| XLSX | `unzip -p file.xlsx xl/sharedStrings.xml` plus the sheet XML, or a short Python pass |
| MD / TXT / CSV | read directly |
| Images / diagrams | read as images — a BPMN screenshot is often the clearest statement of the real flow |
| Pasted text | use as given |

Copy the sources into `$LIB/<pair>/context/`, and write
`$LIB/<pair>/context/extracted.md` — one section per source file, with what it
covers. That file is the audit trail: every `[from your context]` marker on the page
must be traceable to a line in it.

## What to take from it

Work through the material asking what it settles, and record each as a decision:

- **Terminology** — their names for steps, objects, blocks, statuses. These rename the
  same things *everywhere on the page*, including the flow chain, the document cards
  and the quiz.
- **The flow** — their actual step order, their branches, their approval gates. If the
  handbook shows a step the generic flow lacks, add it; if it lacks one the generic
  flow has, remove it rather than keeping both.
- **Glossary definitions** — replace the generic definition with theirs, verbatim in
  meaning. Their definition is what their people will use in the workshop.
- **KPI definitions** — use their formula and their clock. If theirs differs from the
  industry-standard one, keep theirs *and* name the difference in "where it misleads" —
  that gap is often the most useful thing on the page.
- **Systems** — replace `[typical]` systems with the named ones, and drop the marker.
- **Known deviations and pain points** — these become Challenge narratives with a far
  better provenance than any inference; mark them as theirs.

## Provenance on the page

Anything that came from the user's material carries a **`from your context` chip**, and
anything still generic keeps its `[typical]` / `[unverified]` marker. A reader must be
able to tell, at a glance, which parts are the customer's own words and which are the
outside view. Never remove a chip to make the page look more authoritative.

## In the exports

- **PDF** — the chips render as small bordered labels, so a printed page still shows
  whose words are whose.
- **Markdown** — chips become explicit tokens, `` `[source: customer material]` `` and
  `` `[source: industry-typical]` ``, appended to the value they qualify. An agent
  consuming the file can filter on them; it must never have to guess provenance from
  prose.

## Passing it to the agents

Both research agents receive a **condensed excerpt** — the terminology list, the step
names, the systems, the stated pains — with the instruction: *this is the customer's
own material and is authoritative; do not contradict it, research the gaps around it,
and flag anything in it that looks outdated.* This stops an agent from confidently
returning a generic flow that the handbook already disproves.
