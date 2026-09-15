---
description: COMMAND — build a NEW enablement. Researches a process at a company and generates the interactive page. Optional arg — "<Process> at <Company>", plus any paths to folders or files holding the customer's own process detail.
---

Start the process-enablement pipeline.

First, preflight — it is idempotent and takes a moment:

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/setup.sh" --quiet
```

It prints `LIB<TAB><dir>`: that directory is the exploration library, and the skill's
`$LIB` for the whole run. On `BLOCKED<TAB><reason>`, stop and report the reason — the
pipeline cannot run. On `MISSING<TAB>claude<TAB>…`, continue but say so at the end: the
page will generate and read fine, its chat will not work. `CREATED` lines mean this was a
first run — mention that the library was just set up.

Invoke the **`explore`** skill from this plugin (`process-enablement:explore`) and follow
it end to end. It owns the whole pipeline: collecting the inputs, ingesting any material
the user supplies, resolving the industry, running the three research agents in parallel,
reconciling their findings, writing the teaching content, rendering the HTML, starting the
chat bridge, and recording the exploration in the library.

If arguments were given, treat them as the process, the company, and any context paths:
`$ARGUMENTS`. Parse what you can (for example "Order Management at Barilla" → process
"Order Management", company "Barilla") and skip those questions; ask only for what is
missing.

Anything path-shaped — absolute, `~`-relative, or quoted — is **additional context**, not
part of the process or company name: a folder or an individual file where the user keeps
that company's own, more detailed process material. Hand every such path to the skill as
Phase 1b material; a folder means everything readable inside it, recursively. Passing paths
replaces the Phase 1b question, not the ingestion. If a path does not exist or holds nothing
readable, say so and ask rather than continuing without it.

Do not reimplement any of the pipeline here — the skill is the single source of truth for
how it runs.
