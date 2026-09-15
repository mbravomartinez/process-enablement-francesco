---
description: COMMAND — REVIEW enablements already generated. Lists the saved library and reopens one; never researches or generates. Optional arg — a process, company or industry to filter by.
---

Reopen an already-generated **process-enablement** page. Read-only: never research, never
render, never translate, never write to the library. Do **not** invoke the `explore` skill.
If the user wants something new, or a language that does not exist yet, tell them to run
`/process-enablement:start`.

`scripts/library.sh` does all the locating, validating and launching. Do not hunt for
directories, do not read `registry.json` yourself, do not re-verify files on disk.

## 0. Preflight

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/setup.sh" --quiet
```

Idempotent, and the only thing that guarantees a library and a valid `registry.json` exist
before step 1 reads them. Stop and report on `BLOCKED`. A `CREATED` line means there was
no library at all until now — so it is empty by definition: say so and point at
`/process-enablement:start` instead of listing. Note any `MISSING claude` for step 3.

## 1. List

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/library.sh" list "$ARGUMENTS"
```

Tab-separated, newest-`updated` first. `LIB` = resolved library dir; `ALSO` = another
candidate that also holds entries (flag it, never merge); `EMPTY` = nothing usable, so say
the library is empty and point at `/process-enablement:start`.

`E` rows are already validated — stale entries and ungenerated languages are excluded:

```
E  id  process  industry  companies  langs-ok  langs-stale  steps/deviations/kpis/terms  created  updated  grounded|ungrounded
```

`STALE` rows are for the report only; never offer them.

## 2. Open

**Opening the page in the browser is the point of this command** — never stop at a printed
list. If exactly one `E` row (and one ok language) survives, open it without asking. Ask
with `AskUserQuestion` only when there is a genuine choice.

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/library.sh" open <id> [lang]
```

This picks the first free port of 8787/8788/8789, starts the chat bridge on it, prints
`LIB` / `OPENED` / `PORT` / `HEALTH`, and opens the page. A `HEALTH` line reporting
`unreachable` or `"claude": false` means chat won't work — report it; the page still opened
and reads fine without chat.

## 3. Report

One short paragraph: the page opened and its path, the resolved `LIB` (and any `ALSO`), the
languages that directory holds, which languages are *not* generated (and that
`/process-enablement:start` generates them), the bridge port and health, and anything
`STALE`.

Registry hygiene is the one write allowed here, and only if the user asks for it: removing
an entry means restamping the `REGISTRY` constant in every remaining `index*.html` (see
`skills/explore/references/registry.md`). Say so before doing it; never silently.
