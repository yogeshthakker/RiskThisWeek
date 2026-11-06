# This Week in Risk: project notes

A Python tool that finds the week's most impactful developments in Indian banking risk
management for **a foreign bank operating in India**, in six blocks of three items (Credit,
Market, Non-financial risks, Cyber security, Fraud, Compliance), and produces slides and a
web page for the weekly status meeting ("This week in risk"). The user runs it on their own Windows machine.

## Run it

```bash
pip install -r requirements.txt
python risk_week.py --ai --open        # Gemini free tier; --open opens the web page
python -m unittest test_risk_week      # 38 tests, no network or key needed
```

Output goes to `output/`: `risk-week-<date>.pptx`, `.html`, `.md`, and
`risk-week-<date>-ai-reply.json` (the raw AI replies, for checking).

## Files

| File | What it is |
|---|---|
| `risk_week.py` | The whole tool: collect, filter, group, score, AI, write. Standard library only, plus python-pptx for the slide |
| `sources.json` | Feeds, Google News searches and the bank **profile** (what ranks up or down). The user edits this to tune results |
| `cro_desk.txt` | The user's notes for the CRO box, one per line. Git-ignored (may be internal); `cro_desk.example.txt` shows the format |
| `pending_items.txt` | Pending items for the status meeting, `Item \| Owner \| Due \| Status` per line, kept by hand. Git-ignored; `pending_items.example.txt` shows the format |
| `test_risk_week.py` | unittest tests using sample feeds and fake AI replies |
| `.env` | `GEMINI_API_KEY=...` on the user's machine. Git-ignored |

## How it works

1. **Collect** 14 feeds (RBI press releases, notifications, speeches, publications; CCIL;
   SEBI; FSB; UK OFSI; Risk.net; Central Banking; Business Standard; ET Banking; ET BFSI)
   and 23 Google News searches (MSME, India–Russia, Reuters/Bloomberg on RBI, FATF, OFAC,
   foreign-bank topics) for the last 7 days. `fetch`/`parse_feed` handle gzip bodies
   (Risk.net, Central Banking), bare `&` in XML (CCIL) and RSS 1.0/RDF (BIS).
2. **Filter** routine market notices (T-bill auctions, money market operations), non-banking
   items and look-back stories.
3. **Set aside routine enforcement.** A fine or direction aimed at one bank stays out of the
   ranking if it is under `penalty_threshold_crore` (₹10 crore), names no foreign bank and
   restricts no business. These are listed at the end of the page, not dropped.
4. **Group** the same story across outlets (word-stem overlap against every headline in a
   group). Wider coverage ranks higher.
5. **Block and score.** `CATEGORIES` are the six blocks (`BLOCKS`, in display order); a story
   takes the block with the most regex hits (headline hits double; ties go to the earlier
   block, so a draft ECL rule can land in Compliance rather than Credit). Score adds the
   profile's focus / less-relevant terms, peer foreign banks, source weight (RBI first),
   severity words and recency. `pick()` takes the best `top` (default 3) per block;
   `profile.priority.topics` (MSME lending, India–Russia) add `priority.weight` (3.0), and
   `reserve()` puts the best story on a missing topic into its block. `Result.blocks` holds
   the blocks; `Result.top` is all shown items, block by block (`flatten`).
6. **AI (optional, `--ai`).** Gemini `gemini-3.5-flash-lite` over its REST API (no SDK)
   by default; `--provider claude` uses the Anthropic SDK (`claude-opus-5-5`). The AI picks
   3 per block from the best ~7 candidates of each block (it may move a story to another
   block; a block it leaves empty keeps the keyword picks), writes a headline and a "why it matters for us"
   line (at most 30 words) for each, and picks a CRO focus item with what the CRO should ask
   the team. Shown items missing a "why" get one follow-up request. Any failure falls back to the
   keyword ranking, and the output says why.
7. **Write** the slides (1: "From the CRO's desk" panel and "Pending items" table from
   `pending_items.txt`, overdue in red; 2: the six blocks, 3 × 2; 3: "Also on the radar"),
   the HTML page (full width up to 1680px: CRO box and pending items side by side, the
   blocks in a 3 / 2 / 1-column grid, radar and collapsible routine enforcement) and
   Markdown. Every headline is a link (on slides: Slide Show, or Ctrl+click while editing).

## Decisions the user made

- Focus on **impact for a foreign bank**, not routine penalties, co-op banks, microfinance,
  farm loans, local crime, quarterly results or retail product news.
- A **"From the CRO's desk" box**: the user's own notes (`cro_desk.txt` or `--cro "..."`)
  plus one focus item.
- **Risk as an enabler for the business.** The CRO's greatest focus is **MSME lending**,
  then **India–Russia** (payments, rupee–rouble, vostro, sanctions). These are
  `profile.priority.topics` and `profile.guidance` (passed to the AI) in `sources.json`.
- **Pending items** are the CRO's second focus: a hand-kept file shown next to the CRO box.
- **Six blocks of three items**, using the full page width (the user's request of 6 Nov 2026).
- No home-regulator feed: the user said not to add one.
- **AI is optional**; the free **Gemini** tier is the default because it costs nothing.
  Only public news is sent, so the free tier's data use is acceptable here.
- Links must be clickable in every format.

## Open items

- **AI summaries not yet confirmed on a real run after the latest fix.** The user saw two
  items without a "why it matters" line. The fix (other key names accepted, a follow-up
  request for missing ones) was tested only with fake replies. If it recurs, read
  `output/risk-week-<date>-ai-reply.json` first.
- Gemini free-tier limits are per project and shown only in Google AI Studio.
- Google News links are Google redirect addresses; they open fine in a browser.
- Possible next steps the user has not asked for yet: a weekly schedule, sending by email,
  a scraper for RBI's draft-directions page and CERT-In advisories (no feeds; see the source
  research of 6 Nov 2026), BIS feeds (supported by the parser, but mostly research).
- The no-AI ranking still favours general cyber and FEMA stories; with `--ai` the guidance
  steers the pick. A real `--ai` run with the new priorities has not been checked yet.

## History

Built first inside `yogeshthakker/rbi-intel` (an RBI regulatory-intelligence project), then
moved here. `rbi-intel` no longer contains it; its branch `claude/ecstatic-meitner-vusea5`
holds only a Gemini default-model fix. `yogeshthakker/RiskLens2` was emptied and is unused.

## Conventions

- Run the tests before every commit, on Python 3.11 as well (no backslashes inside
  f-string expressions: the user's Python version is unknown). Keep the tool to one file and the standard library
  (python-pptx and anthropic optional).
- Check the slide visually after layout changes (LibreOffice can render it to PDF).
- Never commit `cro_desk.txt`, `pending_items.txt`, `.env` or `output/`.
