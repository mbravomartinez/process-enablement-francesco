# How to teach a process to someone who doesn't know it

Distilled from the Celonis Process Enablement 2.0 decks in
`Enablements content/` — `[OM]` Order Management (45p), `[IM]` Inventory
Management (47p), `[Procurement]` (69p). All three follow the same teaching
pattern. **Copy the pattern; never copy their numbers or customer names.**

Read the PDFs before generating content — including the page images, since the
visual conventions carry as much meaning as the text.

## The deck's own arc

`Purpose & Goals → Landscape → the whole linked flow → each step in its own frame,
with its persona and objects in context → per-problem Concept / Challenge → KPIs →
Glossary`

**Four deliberate departures from the decks.** A deck has a presenter pacing it
one slide at a time; a page does not, so we pace it structurally instead:
- **We show one thing at a time.** Five screens, each with a single job. Where a
  screen holds several items, it is a list plus one explanation — never a tiled
  grid. Nothing is pinned above the navigation. The knowledge is all there; only
  the density is gone.
- **No Solution stage.** The page diagnoses; it does not prescribe.
- **Nothing lives in a pop-up.** Every stage and step explains itself in its frame.
- **No knowledge check and no takeaway slides.** Those exist to close a live
  session. A page the reader can re-read does not need them.

Two consequences worth stating: **personas are taught inside the step that needs
them**, not as an upfront roster, and **the process-intelligence matrix becomes the
grouping of the problem list** rather than a dense tile of its own.

Everything the page renders should follow that order of understanding: *why the
process exists* before *who does it* before *what it produces* before *how it
runs* before *where it breaks*.

## The seven moves that make it teachable

### 0. Everything is a sentence, never a keyword
The decks get away with terse labels because a presenter speaks over them. This
page has no presenter, so every label must carry its own explanation.

- `Input: customer order` → "**Input:** a customer's purchase order, arriving by
  EDI, portal or email, stating which materials they want, in what quantity, to
  which ship-to location, and by when."
- `KPI: On-time delivery rate` → what it measures, how it is calculated in words,
  why a bad value hurts, and which date the clock runs against.
- A term, a system, a persona's accountability, a deviation's damage: all
  sentences.

If a reader would have to ask "…meaning what?", the text is not finished.

### 1. Purpose and Goals, in one breath
> **Purpose:** Process customer orders and ensure goods are delivered and billed
> on time.
> **Goals:** 1. Deliver on Time 2. Minimize Effort to Process Orders
> 3. Increase/Protect Revenue

One sentence for purpose. Exactly three numbered goals. No hedging.

### 2. Place the process in its landscape — by its handovers, not its neighbours
The decks show the nesting (`Lead to Cash` → `Order to Cash` → `Order Management`
between `Quote to Order` and `Accounts Receivable`). Naming the neighbours is not
enough on a page: three boxes side by side look like a list of unrelated processes.

Show the **contact points** instead. For each boundary, name three things:
- **what object crosses it** — a won order comes in, an issued invoice goes out;
- **what it costs this process when that handover is poor** — an incomplete order
  means we start blocked; a late invoice means they collect late;
- **where the boundary actually falls** — this process starts when the PO is accepted
  as a sales order, not when the opportunity was created; it ends when the invoice is
  collectable, not when the cash lands.

Then say what is **deliberately not ours** — winning the deal, setting the price list,
setting the credit limit, chasing overdue cash — and note that each can still block
us. That last sentence is what makes the later Problems screen make sense: a lot of
pain in a process is inherited across a handover, not created inside it.

### 3. Personas as named people with a first-person quote
> **James** — Customer Service Representative — *"I ensure timely order
> processing."*
> **Rob** — Warehouse Clerk — *"I pick, pack, and ship the goods."*

Two to three personas, first name only, one quote each in their own voice. The
quote is what makes the role stick — write it as the person would say it.

### 4. Key Objects, colour-coded, defined in plain words
Three main objects, each with a colour held consistently for the whole page:

| Object | Definition style |
|---|---|
| **Sales Order** (+ Sales Order Item) | "Document that records a customer's request for goods, specifying what they want to buy." |
| **Delivery** (+ Delivery Item) | "Document that records the goods being shipped, including quantities and when and where they'll ship." |
| **Customer Invoice** (+ Invoice Item) | "Bill sent to the customer, listing the goods/service they bought and what they owe." |

Note the shape: *"Document that records …"* — no jargon, no system names, and the
`(+ Item)` header/line distinction shown but not laboured. Close with a footnote
listing the other objects that exist, so the learner knows the three are a
simplification.

### 5a. Show the whole flow linked, before any single step
Before drilling in, give the reader the map: **every step, connected end to end**,
with the arrows drawn — including branches (the condition that diverts a case) and
loop-backs (rework returning to an earlier step). A newcomer must be able to see
where a case enters, where it leaves, and what can send it sideways, all in one
glance. **Draw the sideways paths, do not describe them** — a branch written as a
sentence under the diagram forces the reader to hold two step numbers in their head and
map them back onto boxes. An arc that visibly leaves one node and returns to another
needs no such work. This overview stays visible while they explore individual steps, so they
never lose their place in the chain.

### 5b. Then build the flow one step at a time, around ONE running example
This is the core move. The same order — number `432431`, ship-to `Kroger HQ`,
`$3200`, deliver `2/15/2024`, line items `Snickers 1234 ×100 @ $2` and
`Skittles 9981 ×1000 @ $3` — is carried through every single step. The learner
watches one concrete thing move.

**Each step explains itself inside its frame — never in a pop-up.** The step's
description and its worked example sit in the frame next to the documents, visible
without a click. Clicking a step in the rail or the overview moves the frame to
that step; it does not open a dialog.

Each step frame has three zones plus its own explanatory text:
- **left**: the step list, accumulating — the new step highlighted, earlier ones
  greyed, each with its volume (`4.1M Times`)
- **middle**: the persona who acts at that step
- **right**: the documents, drawn as cards with real field values, stacking up as
  they are created; ticks on item lines as they are fulfilled; a speech bubble for
  a communication event ("We've received your order! We will deliver on Feb.
  15th."); partial deliveries drawn as `Shipment #1` / `Shipment #2`

Invent one example and hold it. Never switch numbers mid-flow.

### 6. Metrics explained on a timeline, not in a formula
Give the timeline room: labels above the axis, zones on it, span names below, and
nothing within touching distance of anything else. A cramped diagram is worse than
no diagram, because the reader spends their attention untangling it instead of
learning from it.

Each key metric gets a real paragraph — what it measures, how it is calculated in
words, why a bad value hurts, which event starts the clock, and the definitional
trap if there is one — then a **structured example** (see below), and then a
**horizontal time axis** with the zones marked —
`Billed On Time` (green) → `Billed Late` (amber) → `Potential Loss` (red), with
the trigger event pinned above the axis (`Shipped`, `Requested or Confirmed
Delivery Date`). The picture is the explanation.

### 7. Opportunities as Concept → Challenge (no Solution)
Two stages, side by side in the same frame — both readable at once, no reveal, no
dialog. **There is no Solution stage.** This page diagnoses; it does not prescribe,
and it carries no vendor pitch.
- **Concept** — define the mechanism first, neutrally: *"Billing Block — used to
  prevent the creation of an invoice until the information is all correct or
  ongoing disputes are resolved."* Include the small diagram: the mismatch
  (`Price: $1,000 ✗` vs `Price: $10,000 ✗`, `Units: 200 ✓`) and the red span on a
  time axis showing the delay.
- **Challenge** — what went wrong at a named company, in plain narrative: *"Due to
  high order volumes, and lack of visibility, TD Synnex consistently lost track of
  orders with billing blocks. Some orders were never invoiced and thus TD Synnex
  never received payment for goods they delivered."*
Concept before challenge, always. Understanding the mechanism is what makes the
challenge legible to a newcomer. Stop at the challenge — the reader now understands
the problem, which is the whole job of this page.

### 7b. Every challenge and every KPI ends in a structured example — strict
The description explains the mechanism; the example proves the reader has understood
it. It is **never a paragraph**. Three or four lines, each `Label: value`, the last
line the effect:

    Standard: raw tomato at €0.18/kg, released before the period
    Actual:   invoiced at €0.21/kg on order 900045678
    Effect:   €132.00 purchase price variance on 4,400 kg

- Built from the **one running case** the page already uses — same order number,
  material, amounts and dates — so nothing new has to be learned to read it.
- A KPI's example shows **its own arithmetic**: standard, actual, variance, in that
  order. The reader watches the number being computed, not described.
- The **last line is always the effect**, in currency, days or percent.
- Never invent a figure. Where research supplied none, name the mechanism and the
  unit instead — an unsourced number is worse than no example.
- The prose stays as it is. The example is added beside the description, never in
  place of it.

## The Process-Intelligence matrix — keep the thinking, drop the tile
The decks' densest slide. Keep what it encodes — that every problem and KPI belongs
to a **business objective** — but render it as the **grouping of the problem list**,
so the reader meets one problem at a time under a named objective. Do not reproduce
the grid. For reference, the original is the **happy path** as a horizontal spine on
top, then a column per **business objective** (Improve Customer
Satisfaction · Increase/Protect Revenue · Optimize Working Capital · Boost
Productivity · Ensure Compliance & Sustainability), each holding **Key Metrics**
and **Improvement Opportunities**. Objectives connect up to the happy-path steps
they attach to. Everything greyed except the column being discussed.

## Voice rules
- Short declarative sentences. Present tense. Active voice.
- Define a term the first time it appears, inline, in one clause.
- Money and volumes as concrete tokens (`$3200`, `4.1M Times`), never "significant".
- Explain the mechanism before naming the pain, and the pain before the fix.
- No Celonis product pitch anywhere. The decks carry boxed `OCPM Benefit` callouts;
  we omit them entirely, along with the Solution stage.
- Nothing hides behind a click. Pop-ups are banned: if a fact matters, it is in the
  frame.

## What NOT to carry over
- **Their numbers.** `4.1M Times`, `1.32M Objects`, `40%` belong to those decks'
  customers. Use the researched company's real figures, or omit the figure.
- **Their customer names.** Rational, TD Synnex, Volkswagen, Alstom, ESAB,
  Cargill, Dürr, Voestalpine, Hitachi Energy are references from those decks. Only
  name a company in a Challenge if research actually surfaced that story, with a
  source.
- **Stock photography.** Render personas as initials in a circle plus name, role
  and quote.
