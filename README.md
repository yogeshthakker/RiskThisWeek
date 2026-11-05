# This Week in Risk

Collects the week's most impactful developments in **Indian banking risk management**, as they
matter to **a foreign bank operating in India**, and turns the top 5 into a ready-to-present
slide for a status meeting.

```bash
pip install -r requirements.txt
python risk_week.py --open
```

This writes three files to `./output/` (`--open` also opens the web page):

| File | Use |
|---|---|
| `risk-week-<date>.pptx` | Slide 1: the top 5. Slide 2: "Also on the radar" (the next 5) |
| `risk-week-<date>.html` | The same as a web page, plus the routine enforcement left out of the ranking |
| `risk-week-<date>.md` | The same as text notes |

**Links.** Every headline links to its article. On the slide, click a headline or "Read ↗"
during Slide Show, or Ctrl+click while editing. On the web page, links open in a new tab.
The terminal summary prints plain web addresses and the page's address.

## Where the news comes from

`sources.json` lists RBI press releases and notifications, SEBI, ET BFSI, and Google News
searches aimed at what a foreign bank watches: RBI draft directions, foreign banks in India,
liquidity and the rupee, FEMA and external commercial borrowing, ECL and Basel capital,
priority sector lending, KYC/AML and sanctions, cyber and outsourcing, data protection,
GIFT City, asset quality and monetary policy. Add, remove or edit any of them; `weight`
makes a source rank higher.

## The bank profile

The `profile` section of `sources.json` describes the bank reading the report. Edit it to
change what counts as relevant:

| Setting | What it does |
|---|---|
| `bank` | One sentence about the bank. It goes into the AI's instructions and its "why it matters" lines |
| `focus.terms` | Topics that rank an item higher: FX/FEMA, cross-border, liquidity and rates, capital and ECL, priority sector lending, sanctions/AML, data and outsourcing, corporate credit, trade finance, global markets, draft RBI rules |
| `less_relevant.terms` | Topics that rank an item lower: co-operative banks, microfinance, gold loans, farm loans, local crime, quarterly results, share prices, retail product news |
| `foreign_banks` | News naming one of these banks ranks higher, and their penalties are never treated as routine |
| `penalty_threshold_crore` | Fines on a single bank below this amount (₹10 crore) are left out of the ranking |

Terms are regular expressions and ignore case, so `co-?operative` matches both spellings.

## How the top 5 are chosen

1. **Filter.** Drops routine notices (T-bill auctions, money market operations, VRRR
   results), items not about banking, and look-back stories about past years.
2. **Set aside routine enforcement.** A fine or direction aimed at one bank is left out of
   the ranking when it is below the threshold, names no foreign bank and restricts no
   business. These are listed at the end of the web page, so nothing is lost.
3. **Group.** The same story from several outlets counts once, and wider coverage ranks it
   higher.
4. **Score.** By risk category (FX and cross-border, regulation, liquidity and markets,
   capital, credit, cyber and fraud, AML/KYC, supervisory action, governance, climate),
   by the bank profile, by source (RBI first), and by severity words and recency. No more
   than two items come from the same category.

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
ranking is used and the output says why.

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
| `--top N` | 5 | Number of items |
| `--out-dir DIR` | `output` | Where the files go |
| `--sources FILE` | `sources.json` | A different source list |
| `--ai` | off | An AI picks and explains the items |
| `--provider` | `gemini` | `gemini` (free tier) or `claude` |
| `--json` | off | Also print the items as JSON |
| `--open` | off | Open the web page in the browser when done |

## Tests

```bash
python -m unittest test_risk_week
```

The tests use sample feeds and need no internet access or API key.

> The items are picked by machine from public news. Check the source before quoting a
> figure or a name.
