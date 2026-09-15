# The exploration library

Every generated exploration is recorded in **`$LIB/registry.json`**, the project's
small database. It is what lets someone come back months later, pick the process and industry from the
header dropdowns, and reopen what was already built instead of paying for it again.
The dropdowns are the only entry point — they list existing pairs only, so a selection
can never point at something that was never generated.

## Identity: one exploration per Process + Industry pair

The **`process` + `industry` pair is the primary key**. Order Management in chilled
dairy and Order Management in generic pharmaceuticals are two different explorations,
because the deviations, systems and terminology genuinely differ. The same pair
studied twice is the *same* exploration — update it, never fork it.

The company is **context, not identity**: it supplies the real systems landscape and
the Challenge narratives, and it is recorded on the entry (with the ability to add
more companies as the pair gets reused). If a second company is studied against an
existing pair, append it to `companies` and refresh the affected sections — do not
create a second directory.

Directory: `$LIB/<process-slug>__<industry-slug>/`, where `$LIB` is the library
directory `scripts/setup.sh` prints (see SKILL.md Phase 0).

## Schema

```json
{
  "schema_version": 1,
  "explorations": [
    {
      "id": "order-management__consumer-goods-confectionery",
      "process": "Order Management",
      "industry": "Consumer Goods — confectionery",
      "companies": ["Example Co."],
      "path": "order-management__consumer-goods-confectionery",
      "languages": [
        { "code": "en", "label": "English",  "file": "index.html",    "generated": "2026-08-24" },
        { "code": "it", "label": "Italiano", "file": "index.it.html", "generated": "2026-08-25" }
      ],
      "steps": 6, "problems": 4, "kpis": 4, "terms": 6,
      "created": "2026-08-24",
      "updated": "2026-08-25",
      "research": ["research/industry.md", "research/company.md"]
    }
  ]
}
```

Every `file` path is relative to the exploration's own `path`, so a page can reach a
sibling with `../<path>/<file>`.

## Only real entries — ever

Every row in the registry, and therefore every option in a header dropdown, must point
at a file that exists on disk. A select that offers a pair with no file behind it takes
the reader to `ERR_FILE_NOT_FOUND`, which is worse than not offering it at all.

- **Append an entry only after the directory and its file are written** — never as an
  intention, never as a placeholder for something planned.
- **Append a language to `languages` only after that `index.<code>.html` exists.** The
  language menu renders only the codes listed there; anything else would 404.
- **Remove an entry whose directory has been deleted** before restamping pages.
- The page's picker also refuses to navigate to an entry with no `path` or no
  `languages`, as a belt-and-braces guard — but the registry should never contain one.
- **The entry `id` is also the browser-storage scope.** Each page declares it as
  `CURRENT_ID` and derives `pe-notes-<id>` and `pe-lang-<id>` from it. Every exploration
  shares one `file://` localStorage origin, so the id is the only thing keeping one
  exploration's Personal Notes out of another's.
- When the project holds a single exploration there is nothing to switch to: the
  generator leaves both selects with one option and `disabled`, with a title explaining
  that it is the only exploration so far. Do not render an empty or teasing dropdown.

## Rules

- **Read it in Phase 0**, before any research. A matching pair with the requested
  language means: open that file and stop.
- **Merge, never overwrite.** Adding a language appends to `languages`; adding a
  company appends to `companies`; both bump `updated`.
- **Keep it sorted** by `updated`, newest first, so the Process select reads as a
  recency list.
- **The page carries its own snapshot.** A `file://` page cannot fetch local JSON
  (CORS blocks it), so the generator stamps a `REGISTRY` constant into every
  `index*.html`. When the registry changes, **restamp every existing page** — otherwise
  older pages offer a library that is missing the newest entries.
- An entry whose directory no longer exists must be removed from the registry rather
  than left to 404.
