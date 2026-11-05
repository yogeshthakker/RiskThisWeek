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

## Optional: AI summaries

```bash
export ANTHROPIC_API_KEY=...
python risk_week.py --ai
```

Claude picks the final 5 from the top candidates and writes a short headline and a
"why it matters" line for each, using only the text of the news items. The default
model is `claude-opus-5-5`; change it with `--model` or `RISK_WEEK_MODEL`. If the call
fails for any reason, the keyword ranking is used and the output says so.

## Options

| Option | Default | |
|---|---|---|
| `--days N` | 7 | Period to cover |
| `--top N` | 5 | Number of items |
| `--out-dir DIR` | `output` | Where the files go |
| `--sources FILE` | `sources.json` | A different source list |
| `--ai` | off | Claude picks and explains the items |
| `--json` | off | Also print the items as JSON |

## Tests

```bash
python -m unittest test_risk_week
```

The tests use sample feeds and need no internet access or API key.

> The items are picked by machine from public news. Check the source before quoting a
> figure or a name.
