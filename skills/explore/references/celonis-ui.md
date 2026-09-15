# Celonis UI styling

The page must look like it belongs inside the Celonis app, not like a generic web
document. Copy the tokens and component rules from `../assets/reference-mock.html`
rather than re-deriving them.

## Tokens

Sampled from the Celonis app UI, not invented:

```css
--bg:#f4f4f6;          /* app canvas — light grey, never white */
--panel:#fff;          /* content surfaces */
--ink:#1a1a1f;         /* primary text */
--ink2:#3f3f46;        /* body text */
--muted:#71717a;       /* labels, secondary */
--line:#e4e4e7;        /* borders */
--line2:#f0f0f2;       /* inner row separators */
--accent:#1a40ff;      /* Celonis BLUE — the primary. Every interactive element */
--accent-ink:#1330cc;  /* hover / pressed */
--accent-soft:#eaeeff; /* selected rows, focus rings */
--magenta:#bb0dc7;     /* process-explorer edges, current node, delay spans */
--deep:#85068d;        /* process-explorer node rings */
--ai:#7e0ae4;          /* AI / agentic accent — use sparingly */
--ok:#1f8a4c; --warn:#b45309; --bad:#e90014;
--r:6px;               /* panel radius; controls use 4px */
```

### The colour split — get this right

**Blue is the primary.** Tabs, buttons, links, selected rows, focus rings, the note
rule in the export — every interactive or system affordance is `--accent` blue.

**Purple and magenta belong to the process data**, never to the chrome: Process
Explorer node rings (`--deep`), edges and the current node (`--magenta`), and the
three business objects. Keeping the families separate is what makes the page read as
Celonis — blue says *you can act on this*, purple says *this is your process*.

Objects therefore take the purple family, so no object ever competes with an
interactive control:

| Object | Colour | Tint |
|---|---|---|
| Sales Order | `--obj1` `#85068d` | `#f7eaf8` |
| Delivery | `--obj2` `#bb0dc7` | `#fdeafd` |
| Invoice | `--obj3` `#7e0ae4` | `#f4eaff` |

Never use blue for a data object, and never use purple for a button.

## The shell

- **Top bar**, 56px, white, one bottom border: the **Celonis mark** (the blob-`C`
  logo, 26×26, `object-fit: contain`), the page
  title at 15px/600, a grey breadcrumb (`› process › company`), the three compact
  selects, then right-aligned: the language icon, **Quiz**, **Export everything as
  PDF**.
- **Underline tabs**, not folder tabs: transparent background, 13.5px, muted text,
  and a 2px **blue** underline plus 600 weight on the active one, sitting on the
  header's bottom border.
- **Panel** with a titled header row (`.panelhead`, 13px/600, one bottom border)
  above a padded body. The header text tracks the active tab, the way a Celonis view
  names itself.
- The canvas is grey; every content surface is a white panel with a 1px `--line`
  border and a 6px radius. Shadows only on the quiz overlay.

## The logo

Use `../assets/celonis-logo.png` — the blob-`C` mark. It must be **embedded as a
`data:image/png;base64,…` URI**, never linked by URL: the page has to render offline
from `file://`, and an external image would leave a broken icon in the top-left the
moment there is no network.

Downscale to 64×64 before encoding (≈2 KB of base64 at 26px display, sharp on
retina). Give it `alt="Celonis"` and explicit `width`/`height` so the header does not
reflow while it decodes. Never recolour it, never place it on a coloured field, and
never substitute a letter in a circle.

## Fills the viewport — the window never scrolls

The page behaves like an app shell, not a document:

- `html, body { height:100% }`, body is `display:flex; flex-direction:column;
  overflow:hidden`. Header and tabs are `flex:none`; `main` is `flex:1; min-height:0`.
- The panel is a flex column with `overflow:hidden`; the **active tab pane is the
  scroll container** (`flex:1; min-height:0; overflow-y:auto; scrollbar-gutter:stable`).
  Content too tall for the frame scrolls inside it — never the window.
- In the Process tab the flow chain is `position: sticky; top:-20px` with a soft
  bottom shadow, so the whole linked process stays in view while the step detail
  scrolls beneath it. The chain itself scrolls horizontally.
- The chat column is `height:100%` with its log as the only scrolling part.
- `min-height:0` on every flex child that contains a scroller — without it the child
  refuses to shrink and the window starts scrolling again.
- **Two escapes from this rule:** `@media print` restores `height:auto; overflow:visible;
  display:block` so the PDF paginates normally, and under 940px the shell unlocks and
  the window scrolls again, because stacked columns cannot fit a phone viewport.

## The browser tab

Ship a favicon, embedded like the logo:

```html
<link rel="icon" type="image/png" href="data:image/png;base64,…">
```

Use `../assets/favicon.png` — the graduation-cap mark, which says *this page teaches*
rather than *this page reports*. Downscale to 64×64 before encoding (≈2 KB of base64;
browsers render it at 16–32 and 64 covers retina). Never link it by URL: a `file://`
page with an external favicon shows a broken tab icon offline.

The source PNG is black with a transparent background, so it reads well on a light tab
strip and can disappear against a very dark one. If that matters, ship a second
`<link rel="icon">` with a light-stroked variant behind
`media="(prefers-color-scheme: dark)"`.

## Type and density

System sans (Inter first), 14px base, 1.55 line-height. Section labels are 10.5px
uppercase, `.08em` tracking, 600 weight, muted — that small-caps label is the most
recognisable Celonis text style, so use it for every field label. Headings are 600,
never 700, with slight negative tracking. Controls are compact: 30–32px high, 4px
radius.

## Process-explorer conventions

The flow chain imitates the real Process Explorer:

- each step is a white 4px-radius box with a thin border, holding a **ring dot** on
  the left (2.5px `--deep` border, white fill), the step name at 12px/600, and a
  small muted line beneath it (`step 3 of 6`, or the volume when research gives one);
- the **current** node switches its border and dot to `--magenta`;
- connectors are 1.5px magenta lines with a solid magenta arrowhead — the same
  treatment for the landscape handovers;
- the whole chain sits on the `#fafafb` sub-surface inside a bordered container.

Object colours stay consistent everywhere: Sales Order `--obj1` (deep purple),
Delivery `--obj2` (magenta), Invoice `--obj3` (violet), each as a tinted card with a
matching border.

## Tables

Header row: 10px uppercase muted labels, no fill, single `--line` bottom border.
Body rows separated by `--line2`. Numeric columns right-aligned and
tabular-numeric. Links purple, underlined on hover.

## Selection and focus

Selected list rows get `--accent-soft` fill plus a 2px blue left border and
`--accent-ink` 600 text. Focus is a 2px `--accent-soft` ring with an `--accent`
border — never the browser default outline, never no indicator.

## What not to do

- No gradients, no glassmorphism, no drop shadows on panels, no rounded-pill
  buttons, no emoji as iconography — inline SVG strokes at 1.6px only.
- No large coloured hero blocks. Celonis views are dense, quiet and grey-on-white;
  colour marks meaning, never decoration.
- Do not put a big number on screen unless research supplied it. The app's giant KPI
  figures are compelling precisely because they are real.
