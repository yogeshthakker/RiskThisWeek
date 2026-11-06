# This Week in Risk

Collects the week's most impactful developments in **Indian banking risk management**, as they
matter to **a foreign bank operating in India**, and arranges them in six blocks of three items:
**Credit, Market, Non-financial risks, Cyber security, Fraud and Compliance**, ready to present
at a status meeting.

```bash
pip install -r requirements.txt
python risk_week.py --open
```

This writes three files to `./output/` (`--open` also opens the web page):

| File | Use |
|---|---|
| `risk-week-<date>.pptx` | Slide 1: "From the CRO's desk" and "Pending items" side by side. Slide 2: the six blocks, three across. Slide 3: "Also on the radar" (the next 6) |
| `risk-week-<date>.html` | The same as a one-screen web page sized for 1920 × 1080: the six blocks in a 3 × 2 grid, with the CRO box, pending items, "also on the radar" and the routine enforcement in a sidebar on the right. Long headlines and summaries are shortened to fit; hover to read them in full, or click to open the article. On smaller screens it becomes a normal scrolling page |
| `risk-week-<date>.md` | The same as text notes |

**Links.** Every headline links to its article. On the slide, click a headline during Slide
Show, or Ctrl+click while editing. On the web page, links open in a new tab.
The terminal summary prints plain web addresses and the page's address.

## From the CRO's desk

A highlighted box on the slide, and at the top of the page, holds what the CRO should see first:

1. **Your notes.** Copy `cro_desk.example.txt` to `cro_desk.txt` and write one note per line,
   for example "Risk Appetite Statement review goes to the Board on 20 Nov". They can be
   news or any update from the CRO's desk. You can also add a note for one run:
   `python risk_week.py --cro "RBI inspection data requests due Friday"` (repeatable).
   `cro_desk.txt` is not committed to git, so internal notes stay on your machine.
2. **Focus this week.** One news item to act on first. With `--ai`, Gemini picks it from the
   items shown and writes what the CRO should ask the risk team to check or do, framed so risk
   enables the business. Without AI, it is the top item on the first priority topic
   (MSME lending), or else the top-ranked item.

## Pending items

A table of open actions for the status meeting: its own slide, and a section near the top of
the page. Copy `pending_items.example.txt` to `pending_items.txt` and keep it up to date by
hand, one item per line:

```
MSME credit policy: revised scorecard to Credit Committee | Credit Risk | 15 Nov 2026 | In progress
```

The columns are Item, Owner, Due date and Status; only the item is required. Dates can be
written `15 Nov 2026` or `2026-11-15`. An item past its due date that is not `Done` shows
as **Overdue**, in red, at the top; done items go to the bottom (delete them when they no
longer need showing). `pending_items.txt` is not committed to git.

## Where the news comes from

`sources.json` lists:

- **Official:** RBI press releases, notifications, speeches and publications; CCIL
  notifications and announcements (margins and settlement for FX, NDF and rates); SEBI; the
  FSB; UK OFSI (sanctions).
- **Specialist and business press:** Risk.net, Central Banking, Business Standard finance,
  ET Banking, ET BFSI.
- **Google News searches** aimed at the CRO's priorities and what a foreign bank watches:
  MSME lending (credit guarantees, TReDS), India–Russia payments and sanctions, Reuters and
  Bloomberg on RBI, FATF and OFAC, foreign banks in India, RBI draft directions, FEMA and
  ECB, ECL, rupee hedging, liquidity, cyber (CERT-In), GIFT City and data protection.

Add, remove or edit any of them; `weight` makes a source rank higher. A source that cannot be
read is named at the end of the page; the rest still run.

## The bank profile

The `profile` section of `sources.json` describes the bank reading the report. Edit it to
change what counts as relevant:

| Setting | What it does |
|---|---|
| `bank` | One sentence about the bank. It goes into the AI's instructions and its "why it matters" lines |
| `guidance` | The CRO's current priorities in plain words, passed to the AI (now: risk as an enabler for the business, MSME lending first, then India–Russia) |
| `priority.topics` | The CRO's priority topics, each a list of terms: **MSME lending** and **India–Russia**. A matching item ranks well above other focus topics (`priority.weight`), and each topic gets at least `min_per_topic` place in the report whenever a story exists |
| `focus.terms` | Topics that rank an item higher: FX/FEMA, cross-border, liquidity and rates, capital and ECL, priority sector lending, sanctions/AML, data and outsourcing, corporate credit, trade finance, global markets, draft RBI rules |
| `less_relevant.terms` | Topics that rank an item lower: co-operative banks, microfinance, gold loans, farm loans, local crime, quarterly results, share prices, retail product news |
| `foreign_banks` | News naming one of these banks ranks higher, and their penalties are never treated as routine |
| `penalty_threshold_crore` | Fines on a single bank below this amount (₹10 crore) are left out of the ranking |

Terms are regular expressions and ignore case, so `co-?operative` matches both spellings.

## How the items are chosen

1. **Filter.** Drops routine notices (T-bill auctions, money market operations, VRRR
   results), items not about banking, and look-back stories about past years.
2. **Set aside routine enforcement.** A fine or direction aimed at one bank is left out of
   the ranking when it is below the threshold, names no foreign bank and restricts no
   business. These are listed at the end of the web page, so nothing is lost.
3. **Group.** The same story from several outlets counts once, and wider coverage ranks it
   higher.
4. **Block and score.** Each story goes to one block, by the words it uses:

   | Block | For example |
   |---|---|
   | Credit | asset quality, ECL and provisioning, capital, MSME lending, TReDS, credit guarantees, priority sector |
   | Market | liquidity, rates, the rupee and FX, hedging and NDF, bonds, CCIL clearing |
   | Non-financial risks | governance and conduct, outsourcing and third parties, outages, data protection, climate and ESG |
   | Cyber security | cyber attacks, breaches, ransomware, CERT-In advisories |
   | Fraud | frauds, scams, mule accounts, digital arrests |
   | Compliance | RBI directions and drafts, KYC/AML, sanctions, FEMA, penalties |

   It is then scored by the bank profile, by source (RBI first), and by severity words and
   recency. The best 3 in each block are shown; a block with nothing relevant says so.
5. **Make room for priorities.** If no MSME or India–Russia story is shown but one exists,
   the best one replaces the lowest-ranked other item in its block.

With `--ai`, the AI makes the final pick of 3 per block and may move a story to a better
block.

No AI is needed for any of this.

## Optional: AI summaries (free with Gemini)

Get a free key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey), put it in a
`.env` file next to `risk_week.py`:

```
GEMINI_API_KEY=your-key
```

then run:

```bash
python risk_week.py --ai
```

Gemini picks the final 5 from the top candidates and writes a short headline and a
"why it matters for us" line for each, using only the text of the news items. It is
told which bank it writes for (the profile's `bank` sentence) and to pass over routine items. The default
model is `gemini-3.5-flash-lite`, which is on Google's free tier. One run makes one
request, far inside the free daily limit (your project's limit is shown in AI Studio).
Nothing extra needs installing for Gemini.

If the call fails for any reason (no key, daily limit reached, no network), the keyword
ranking is used and the output says why. If an item comes back without a "why it matters"
line, one short follow-up request fills it in. Every AI reply is saved as
`output/risk-week-<date>-ai-reply.json`, so you can see exactly what the AI returned.

On the free tier Google may use what is sent to improve its products. This tool sends
only public news headlines and summaries, so that is fine here; don't reuse a free key
for confidential bank documents.

To use Claude instead: set `ANTHROPIC_API_KEY`, `pip install anthropic`, and run
`python risk_week.py --ai --provider claude` (default model `claude-opus-5-5`).
Change either model with `--model` or `RISK_WEEK_MODEL`.

## Options

| Option | Default | |
|---|---|---|
| `--days N` | 7 | Period to cover |
| `--top N` | 3 | Items per block |
| `--out-dir DIR` | `output` | Where the files go |
| `--sources FILE` | `sources.json` | A different source list |
| `--ai` | off | An AI picks and explains the items |
| `--provider` | `gemini` | `gemini` (free tier) or `claude` |
| `--json` | off | Also print the items as JSON |
| `--open` | off | Open the web page in the browser when done |
| `--cro TEXT` | none | A note for the CRO box (repeatable) |
| `--cro-file FILE` | `cro_desk.txt` | File with CRO notes, one per line |
| `--pending-file FILE` | `pending_items.txt` | Pending items: `Item \| Owner \| Due \| Status` per line |

## Tests

```bash
python -m unittest test_risk_week
```

The tests use sample feeds and need no internet access or API key.

> The items are picked by machine from public news. Check the source before quoting a
> figure or a name.
