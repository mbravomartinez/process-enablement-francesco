---
description: COMMAND — first-run setup and health check. Creates your exploration library and reports any missing dependency. Idempotent. Also the way to hard-reset the library back to empty, with confirmation.
---

Set up, check, or reset this plugin for the current machine. Arguments: `$ARGUMENTS`
(`reset` asks for a hard reset; anything else is a normal setup/health check).

## Normal run — setup or health check

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/setup.sh"
```

The script does all the work — creating the library, repairing a missing registry,
restoring executable bits, probing dependencies. Do not create directories, write the
registry, or install anything yourself.

Read its tab-separated lines:

| Line | Meaning |
|---|---|
| `LIB<TAB>dir` | the exploration library root — everything this plugin generates lives here |
| `CREATED<TAB>lib\|registry` | what this run had to create; absent means it was already set up |
| `EXISTING<TAB>n<TAB>ids` | what the library already holds |
| `OK<TAB>tool<TAB>version` | present, nothing to do |
| `MISSING<TAB>tool<TAB>why` | needed and absent — report it with the fix the line names |
| `OPTIONAL<TAB>tool<TAB>when` | only needed for the case the line names; mention briefly |
| `CORRUPT<TAB>registry<TAB>…` | an unreadable registry was moved aside and replaced |
| `READY` / `BLOCKED<TAB>reason` | whether the pipeline can run at all |

Report in one short paragraph: whether this was a first-time setup or already configured,
where the library is (and that `PE_HOME` moves it), anything `MISSING` with its install
command, and — if `BLOCKED` — that `/process-enablement:start` cannot run until it is fixed.
Call out `MISSING claude` specifically: pages still generate and read fine, but their
built-in chat stays dark until a `claude` CLI is on `PATH`.

**Already set up and nothing is wrong?** Say so in one line — do not re-explain the whole
report. Then, only if the library is non-empty, mention that
`/process-enablement:setup reset` wipes it back to empty. Never volunteer a reset as a fix
for a `MISSING` tool; installing the tool is the fix.

## Hard reset — only when the user asks for it

Running setup again is *not* a reset: it never deletes anything. A reset is a separate,
explicit act, and it is destructive — it throws away every exploration in the library:
research, content, generated pages, context files, the registry.

**1. Show what would be lost.** This never destroys anything; it exits `3` with
`CONFIRM-REQUIRED`:

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/setup.sh" --reset
```

**2. Ask, and wait.** Use `AskUserQuestion` — the exploration count and the ids from
`EXISTING` in the question, so they see exactly what they are discarding. Offer:

- **Reset, keep a backup** (recommended) — the library is moved aside to
  `output.backup-<timestamp>` next to it, so it can be restored by moving it back.
- **Reset and delete permanently** — no backup, unrecoverable.
- **Cancel** — nothing happens.

Never skip this question, never infer consent from an earlier message, and never treat a
bare `/process-enablement:setup` (or the word "setup") as consent. If the user already said
"yes, wipe it" in the same turn, still show them the `EXISTING` list and confirm the backup
choice — a reset is cheap to redo and impossible to undo. If `EXISTING` is `0`, there is
nothing to reset: say so and stop.

**3. Only after they choose:**

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/setup.sh" --reset --yes            # keeps a backup
"$CLAUDE_PLUGIN_ROOT/scripts/setup.sh" --reset --yes --purge    # deletes outright
```

Report the `RESET` line verbatim — with a backup, give the exact path and say that moving
that directory back over `output/` restores everything. Then point at
`/process-enablement:start`.

## Read-only inspection

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/setup.sh" --status
```

Creates nothing and changes nothing — use it when the user only wants to know what is in
the library or whether the environment is healthy.
