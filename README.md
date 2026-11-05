# This Week in Risk

Collects the week's most noteworthy happenings in **Indian banking risk management** and
turns the top 5 into a ready-to-present slide for a status meeting.

```bash
pip install -r requirements.txt
python risk_week.py
```

This writes three files to `./output/`:

| File | Use |
|---|---|
| `risk-week-<date>.pptx` | Slide 1: the top 5, each linked to its source. Slide 2: "Also on the radar" (the next 5) |
| `risk-week-<date>.html` | The same content as a web page, for email or a browser |
| `risk-week-<date>.md` | The same content as text notes |

## Where the news comes from

`sources.json` lists RBI press releases and notifications, SEBI, ET BFSI, and ten Google
News searches (for example "RBI penalty bank", "bank fraud India" and "bank NPA asset
quality India"). Add, remove or edit any of them; `weight` makes a source rank higher.

## How the top 5 are chosen

1. **Filter.** Drops routine notices (T-bill auctions, money market operations, VRRR
   results), items not about banking, and look-back stories about past years.
2. **Group.** The same story from several outlets counts once, and wider coverage ranks
   it higher. Routine RBI enforcement notices become one "enforcement round-up" item.
3. **Score.** By risk category (enforcement, regulation, credit, liquidity, capital,
   cyber and fraud, AML/KYC, governance, climate), source (RBI first), severity words
   and recency. No more than two items come from the same category.

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
"why it matters" line for each, using only the text of the news items. The default
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

## Tests

```bash
python -m unittest test_risk_week
```

The tests use sample feeds and need no internet access or API key.

> The items are picked by machine from public news. Check the source before quoting a
> figure or a name.
