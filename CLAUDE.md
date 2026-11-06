# This Week in Risk: project notes

A Python tool that finds the week's most impactful developments in Indian banking risk
management for **a foreign bank operating in India**, in six blocks of three items (Credit
risk, Market risk, Non-financial risk, Cyber security risk, Fraud risk, Compliance risk), and produces slides and a
web page for the weekly status meeting ("This week in risk"). The user runs it on their own Windows machine.

## Run it

```bash
pip install -r requirements.txt
python risk_week.py --ai --open        # Gemini free tier; --open opens the web page
python -m unittest test_risk_week      # 42 tests, no network or key needed
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
   block, so a draft ECL rule can land in Compliance risk rather than Credit risk). Score adds the
   profile's focus / less-relevant terms, peer foreign banks, source weight (RBI first),
   severity words and recency. `pick()` takes the best `top` (default 3) per block;
   `profile.priority.topics` (MSME lending, India–Russia) add `priority.weight` (3.0), and
   `reserve()` puts the best story on a missing topic into its block. `Result.blocks` holds
   the blocks; `Result.top` is all shown items, block by block (`flatten`).
6. **AI ranks first (`--ai`); keywords are the fallback** (the user's decision, 6 Nov 2026).
   Gemini `gemini-3.5-flash-lite` over its REST API (no SDK) by default; `--provider claude`
   uses the Anthropic SDK (`claude-opus-5-5`). `run()` sends up to `AI_POOL` (150) stories,
   newest first, with source, date, outlet count and summary but **no keyword block or score**
   (~7k tokens). `explain()` returns an `AiPick`: the AI rates impact 1–10 (`Story.impact`,
   shown "Impact n/10"), assigns blocks, picks `top` per block (ordered by impact; a block it
   leaves empty stays empty), the radar (`radar` ids) and the **story of the week** (`cro_focus`: the
   single highest-impact item, giving the CRO visibility in the bank or an action point for
   the branch) with an action point. Stories are changed only once the reply is accepted (at
   least one valid pick). Shown items missing a "why" get one `fill_why` request. Any failure
   or unusable reply falls back to the keyword ranking (steps 2–5), and `Result.ai` / the
   "ranked by" line says why. Without AI the story of the week is the highest-scoring story.
   Steps 2–5 always run: they filter noise and trim the pool sent to the AI.
7. **Write** the slides (1: "For CRO's desk" panel (story of the week, why, action point,
   then the user's notes small) and "Pending items" table from
   `pending_items.txt`, overdue in red; 2: the six blocks, 3 × 2; 3: "Also on the radar"),
   the HTML page and Markdown. The page is a **one-screen dashboard** on screens at least
   1200 × 700 (target 1920 × 1080, no page scroll): the six blocks 3 × 2 on the left, a
   sidebar with the CRO box, pending items, radar and routine enforcement on the right
   (the sidebar scrolls on its own if long). Headlines are clamped to 2 lines; summaries
   to 2 lines (1 below 1000px of height, hidden below 800px); hovering shows the full
   text. Smaller screens get a scrolling page (CRO box and pending items first, blocks in
   2 or 1 columns). After changing the page, check with Playwright at 1920 × 1080 and
   1920 × 940 (a browser with toolbars) that nothing is cut off. The page and the slides take
   the same content. Every headline is a link (on slides: Slide Show, or Ctrl+click while editing).

## Decisions the user made

- Focus on **impact for a foreign bank**, not routine penalties, co-op banks, microfinance,
  farm loans, local crime, quarterly results or retail product news.
- A **"For CRO's desk" box** (renamed from "From the CRO's desk" on 6 Nov 2026). Its
  emphasis is one **story of the week**: the max-impact story, giving the CRO visibility
  inside the bank or an action point within the branch. The user's own notes
  (`cro_desk.txt` or `--cro "..."`) follow in smaller type. The story is starred in its block.
- Block names end in "risk": Credit risk, Market risk, and so on.
- **Risk as an enabler for the business.** The CRO's greatest focus is **MSME lending**,
  then **India–Russia** (payments, rupee–rouble, vostro, sanctions). These are
  `profile.priority.topics` and `profile.guidance` (passed to the AI) in `sources.json`.
- **Pending items** are the CRO's second focus: a hand-kept file shown next to the CRO box.
- **Six blocks of three items**, using the full page width, and the whole page on one
  1920 × 1080 screen without scrolling (the user's requests of 6 Nov 2026).
- No home-regulator feed: the user said not to add one.
- **AI first, local fallback**: the AI does the ranking and impact judgement; the keyword
  ranking is the fallback. AI stays optional (no key = keyword ranking).
- The free **Gemini** tier is the default because it costs nothing. Only public news plus
  `profile.bank` and `profile.guidance` from `sources.json` are sent; `cro_desk.txt` and
  `pending_items.txt` never are (`TestPrivacy` checks this).
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
- A real `--ai` run with AI-first ranking has not been checked yet (no API key in the cloud
  sandbox). Read `output/risk-week-<date>-ai-reply.json` after the first run.
- Which free LLM API is best for this was researched on 6 Nov 2026 (see the session); the
  default model may change.

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
