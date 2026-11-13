# This Week in Risk: project notes

A Python tool that finds the week's most impactful developments in Indian banking risk
management for **a foreign bank operating in India**, in six blocks of three items (Credit
risk, Market risk, Non-financial risk, Cyber security risk, Fraud risk, Compliance risk), and produces slides and a
web page for the weekly status meeting ("This week in risk"). The user runs it on their own Windows machine.

## Run it

```bash
pip install -r requirements.txt
python risk_week.py --ai --open        # Gemini free tier; --open opens the web page
python -m unittest test_risk_week      # 100 tests, no network or key needed
```

Output goes to `output/`: `risk-week-<date>.pptx`, `.html`, `.md`, and
`risk-week-<date>-ai-reply.json` (the raw AI replies, for checking), `risk-week-<date>-events.html` (all upcoming events).

## Files

| File | What it is |
|---|---|
| `risk_week.py` | The whole tool: collect, filter, group, score, AI, write. Standard library only, plus python-pptx for the slide |
| `sources.json` | Feeds, Google News searches and the bank **profile** (what ranks up or down). The user edits this to tune results |
| `cro_desk.txt` | The user's notes for the CRO box, one per line. Git-ignored (may be internal); `cro_desk.example.txt` shows the format |
| `pending_items.txt` | Pending items for the status meeting, `Item \| Owner \| Due \| Status` per line. Every run shows them and asks for updates first (`review_pending`: number = edit, `a` add, `d N` done, `x N` delete, Enter = carry on; saved with `save_pending`, header comments kept); skipped with `--no-prompt` or when stdin is not a terminal. Git-ignored; `pending_items.example.txt` shows the format |
| `events.json` | Upcoming conferences and programmes (`events`, dated) and ones to watch (`watch`, no date yet). Public, committed; the user edits it |
| `top 20.txt` | The bank's borrowers for the credit portfolio watch, `Name \| alias` per line. **Git-ignored** (`top*.txt`); `top20.example.txt` shows the format |
| `docs/architecture.png` / `.html` / `.mmd` | Architecture diagram (13 Nov 2026): the PNG is drawn from the HTML (Playwright screenshot of `#c` at 1740 px wide, scale 2); the Mermaid copy is in the README. Update them when the flow changes |
| `test_risk_week.py` | unittest tests using sample feeds and fake AI replies |
| `test_headlines.json` | One week's real headlines (6 Nov 2026), used to test the same-story grouping |
| `.env` | `GEMINI_API_KEY=...` on the user's machine. Git-ignored |
| `Confluence PAT.txt` | On the user's machine only, **never committed** (git-ignored). One file, two pages: `NEWS_PAGE_ID` (publish target; alias of `PAGE_ID`) and `ISE_PAGE_ID` (the RBI compliance / ISE page, read only; alias of `COMPLIANCE_PAGE_ID`), plus `CONFLUENCE_BASE_URL`, `PAT`, `VERIFY_SSL`, `CONFLUENCE_TIMEOUT` as `KEY = value` lines. `confluence.example.txt` is the template |

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
4. **Group locally, so the AI gets unique stories only** (the user's request, 6 Nov 2026).
   First `group()`: word-stem overlap against every headline in a group. Then
   `merge_same_story()`: the same news in different words, by a cosine score over words
   weighted by rarity that week (log IDF over stories; `COMMON_WORDS` weigh 0; `SAME_WORD`
   synonyms, hyphenated words joined) plus "anchor" words shared by at most 5 stories:
   merge if score ≥ 0.42, or ≥ 0.33 with 1 anchor, or ≥ 0.28 with 2 anchors (union-find;
   skipped below 20 stories). Tuned on 6 Nov 2026 news: 206 → 189 stories, no wrong merges
   seen (closest: two related bond-fundraising stories). `test_headlines.json` holds that
   week's headlines for `TestSameStory`. Wider coverage ranks higher; the AI sees "N outlets".
5. **Block and score.** `CATEGORIES` are the six blocks (`BLOCKS`, in display order); a story
   takes the block with the most regex hits (headline hits double; ties go to the earlier
   block, so a draft ECL rule can land in Compliance risk rather than Credit risk). Score adds the
   profile's focus / less-relevant terms, peer foreign banks, source weight (RBI first),
   severity words and recency. `pick()` takes the best `top` (default 3) per block;
   `profile.priority.topics` (MSME lending, India–Russia) add `priority.weight` (3.0), and
   `reserve()` puts the best story on a missing topic into its block. `Result.blocks` holds
   the blocks; `Result.top` is all shown items, block by block (`flatten`).
6. **AI ranks first (`--ai`); keywords are the fallback** (the user's decision, 6 Nov 2026).
   Gemini **`gemini-3.8-flash`** over its REST API (no SDK) by default. A busy model (5xx
   such as 503 "high demand", or a network error: `Busy`) is retried after 10 s and 30 s;
   then, or at once on a 429 daily limit, 404, or cut-off/unreadable JSON, the request goes to
   `gemini-3.5-flash-lite`
   (`GeminiProvider.label` records which model answered; it shows in "ranked by"). No
   `temperature` (ignored by Gemini 3.6+, may be rejected later); `maxOutputTokens` at least
   16384 because on Gemini 3 it covers thinking too. `--provider claude`
   uses the Anthropic SDK (`claude-opus-5-5`). `run()` sends up to `AI_POOL` (150) stories,
   newest first, with source, date, outlet count and summary but **no keyword block or score**
   (~7k tokens). `explain()` returns an `AiPick`: the AI rates impact 1–10 (`Story.impact`,
   shown "Impact n/10"), assigns blocks, picks `top` per block (ordered by impact; a block it
   leaves empty stays empty), a **"why it matters" of two or three sentences, at most `WHY_WORDS`
   (55) words: what happened, what it means for us, what to check or act on** (user, 13 Nov 2026;
   was 30 words; kept up to `WHY_CHARS` (450) characters in Confluence, Markdown and console; the
   page clamps it, the slide shortens it), the radar (`radar` ids) and the **story of the week** (`cro_focus`: the
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

8. **Confluence** (user's request, 6 Nov 2026). After the files are written, if `Confluence
   PAT.txt` has a PAT, `publish_confluence()` GETs the page (`/rest/api/content/{id}?expand=
   body.storage,version`, `Authorization: Bearer <PAT>`) and PUTs a new version. The body is
   storage-format XHTML from `to_confluence()`, **news first, compliance last** (user, 13 Nov
   2026): info panel (For CRO's desk), the 2 × 3 table of blocks, radar, expand for routine
   enforcement, then pending items, then the ISE items (status macros). **One entry per run** (user's choice, 13 Nov 2026;
   before that one per ISO week): each sits between anchor macros `rtw-week-<key>` /
   `rtw-end-<key>`, key = run time `YYYYMMDDTHHMM` (old entries `YYYY-Www` are still read and
   sort as that week's Monday 00:00, below its runs). The h2 is "Report of 13 Nov 2026, 15:32";
   `build_confluence_body()` keeps the latest run on top and the rest under "Previous reports"
   in expand macros titled from their h2, replaces only a run in the same minute, and keeps
   `KEEP_REPORTS` / `KEEP_WEEKS` (52).
   409 is retried once. Errors never stop the run. **Guards** (`publish_problems`, added
   11 Nov 2026 after the user's settings file had two `PAGE_ID` lines and the second was the
   ISE compliance page): refuse when a key is duplicated with different values (`_DUPLICATES`),
   when `PAGE_ID == COMPLIANCE_PAGE_ID`, or when `foreign_content()` finds > 40 characters on
   the page not written by this tool, unless `--confluence-replace`. `--confluence-check` (read-only),
   `--no-confluence`, `--confluence-dry-run`. Tested only against a fake server: the user's
   Confluence (internal host) is not reachable from the cloud sandbox.

9. **Pending RBI compliance items** (user's request, 11 Nov 2026). If `Confluence PAT.txt` has
   `COMPLIANCE_PAGE_ID`, `load_compliance()` GETs that page at the start (read only, never sent
   to the AI) and `parse_compliance()` reads every table with an "Observation" column plus a
   deadline or "Compliant/Non-Compliant" column (`_TableReader`: stdlib HTMLParser, rowspan /
   colspan filled, only a status macro's title kept; `_column_map` matches headings loosely).
   The user's headings: Sub-section, Observation, CBS / Non-CBS, Department, Head of
   Department, Comments received from departments, Official deadline, Compliant/Non-Compliant
   submitted to RBI (15.04.2026). Done = status exactly in `COMPLIANCE_DONE` ("compliant",
   "closed", "complied"); overdue = open and past the deadline (`dd.mm.yyyy` parsed). Shown
   as `Result.compliance` (open items, overdue first) in the sidebar, a slide after slide 1,
   Markdown, console and the weekly Confluence page. Any problem is reported, never fatal.
   **Department filter** (user's request, 11 Nov 2026): only rows whose Department contains
   the whole word `ISE_DEPARTMENT` (default "risk", any case; `""` = all; alias
   `COMPLIANCE_DEPARTMENT`). `info` has `page_total` (all rows) and `total` (filtered); titles
   read "Pending RBI compliance items · Risk"; no matching rows is reported with the
   departments found. Deadlines are read by `_first_date` (dd.mm.yyyy, dd/mm/yy, ISO, "15th Apr'26", "April 15,
   2026", month + year = end of month); `--confluence-check` reports open items whose deadline
   was not understood, with examples. **First real check (11 Nov 2026):** the ISE 2025 page
   (id 19000597275) gave 119 observations, 64 compliant, 55 open, 0 overdue; "0 overdue"
   looked unlikely, so the date reader was widened and the check now shows unread deadlines.
   The news page was then moved to a dedicated empty page "This week in Risk". With the
   department filter: 28 risk rows, 5 compliant, 23 open, 10 overdue; 7 deadlines unread
   (typos like "Septemebr", now read by month prefix; "RMP" is not a date).
   **RMP** (user, 11 Nov 2026): "RMP" in the deadline = risk mitigation plan, the most severe
   items, each with its own deadline kept elsewhere. `ComplianceItem.rmp` (`_RMP` matches "RMP"
   or "risk mitigation plan"); never overdue, not counted as an unread deadline; `severe`
   (RMP or overdue) is shown in red. Order (user's choice): **RMP first, then overdue**, then
   by deadline. Counts via `_ise_counts`: "23 open, 3 on RMP, 10 overdue".

10. **MCP server for GigaCode** (user's idea, 11 Nov 2026: GigaCode has no API key, but can add
   MCP servers). `python risk_week.py --mcp` runs `McpServer` (stdlib JSON-RPC over stdio, one
   message per line; stdout carries only protocol, tool code prints to stderr). Tools:
   `risk_week_prepare` (`prepare_week()` + `ranking_prompt()`; returns the same system prompt
   and candidates as the Gemini path, plus an answer example), `risk_week_publish`
   (`parse_ranking()` on the client's JSON, then `finish_week()`, ISE / pending / CRO notes
   added locally, `write()`, `confluence_step()`; replies with a short summary only, no pending,
   notes or ISE content), `risk_week_run` (user, 13 Nov 2026: choose Gemini or MCP from the chat;
   `ranker` "gemini" (default; `self.gemini()` factory, keyword fallback with the reason when it
   cannot be built or fails) or "keywords"; same `_finish()` as publish), `risk_week_check`. State (week, pool) lives in the server process; one
   report per prepare. `run()` = `prepare_week()` + `explain()` + `finish_week()`; feeds are
   fetched with 8 threads (~8 s live). **Batch codes** (11 Nov 2026, after the user's local
   assistant drove the tools from a temp script that restarted the server per call, so prepare
   ran twice and the numbering shifted by up to 2 between the ranked list and the published
   one): prepare returns `Batch: <8 hex>` (sha1 of the pool's links) and pickles the week to
   `output/.risk-week-mcp-batch.pickle`; publish requires `batch`, loads the saved pool if the
   process is new, refuses an unknown or replaced batch, and refuses when `ranking_mismatches()`
   finds > 1/4 of picks whose headline shares no non-common word with the story their id names.
   **Paging** (13 Nov 2026, after GigaCode showed a 33,000-character prepare reply with items 3–51
   missing): prepare returns the instructions plus page 1 (`MCP_PAGE` = 25 candidates, `page_size`
   arg); `risk_week_candidates(batch, page)` returns the rest (~5k chars each, same ids). Each page
   says "Page n of N · ids a–b of T" at the top and what to call next at the end, so a cut reply
   still shows where it is. Live: prepare 10.4k chars, pages 2–6 about 4.5k each.
   The first GigaCode-driven ranking (11 Nov) put a co-op bank supersession in Non-financial
   risk and the UK sailor detention (Russian oil) at 9 in Compliance risk.

11. **Safety net** (user's request, 13 Nov 2026, after both Gemini's fallback and the
   GigaCode-driven ranking picked a co-op bank story and rated a UK sailor detention 9/10).
   `finish_week()` runs `apply_rules()` on every accepted AI ranking: removes picks whose lead
   title matches `profile.exclude` (sources.json; not when `KEEP_ANYWAY` (FEMA, sanctions,
   PMLA, FATF, OFAC) or a priority topic also matches), removes `_foreign_detention()` stories
   (`DETENTION` and `FOREIGN` in the title, not an Indian court), replaces only removed picks
   from the keyword ranking of the same block, drops picks the AI rated `MAX_DROPPED_IMPACT` (4)
   or lower without replacing them (user, 13 Nov 2026, after Gemini's fallback showed "Metro Bank
   UK put up for sale" at 4/10), and re-picks the story of the week when it is
   gone or a detention / court story (highest impact, India preferred; action point dropped).
   Changes go to `Result.ai` ("safety net: N change(s)") and `ai_log`. On 13 Nov 2026 live
   news the list matched 13 of 159 stories (all correct after the FEMA exemption).

12. **Events & reports** (user's request, 13 Nov 2026: "not only news but upcoming seminars /
   conferences or interesting reports"). Three lists, shown in the sidebar under the radar, on a
   slide of their own (last), in Markdown, console and Confluence (after routine enforcement):
   **Comments due** (`read_rbi_drafts`: RBI's draft-directions page, each press release read for
   "on or before <date>"; open or undated drafts of the last 30 days), **Upcoming** (`events.json`
   plus `read_cafral_events`: CAFRAL event pages' `atc_*` vars; within `events.window_days` (60),
   deduped by name) and **New reports** (`pick_reports`: `sources.json` `reports` feeds and
   queries, `Item.kind == "report"`, never in the six blocks; must match a risk block). Upcoming
   shows the nearest `events.max` (10) of the 60-day window (user, 13 Nov 2026: "show top 10,
   keep the 22 handy on a clickable link"): `write()` adds `<stem>-events.html`
   (`to_events_html`, all events), linked from the page panel, the slide and Markdown; the
   console prints its file link; Confluence gets an expand with all of them (a table: When, Event, Place, Organiser, Topics). In Confluence the section is a table grouped in blocks, like the news (user, 13 Nov 2026): Comments due | Upcoming | New reports, each entry a bold link with its meta in italics; comments due carry a status badge ("13 days left", red at 7 or fewer). events.json was filled from a research agent's validation of
   the user's list (13 Nov 2026): 33 dated events (NIBM, IIBF, IACPM, Risk Live, GARP, IOD,
   AIMA, Global Insight), 17 under `watch` (no 2027 date yet, or unverified). Any
   failure goes to the errors list, never fatal. Nothing here goes to the AI.

13. **Credit portfolio watch** (user's request, 13 Nov 2026: "a news analyzer on my credit
   portfolio", names in `top 20.txt`). The user's choices: Google News search per name (names
   only, quoted; never to Gemini), a section in the weekly report (page sidebar after pending
   items, slide after slide 1, Markdown, console, Confluence after the radar), local rules plus
   GigaCode. `load_portfolio` (utf-8 or cp1252, numbering stripped, `|` aliases),
   `scan_portfolio` (search + the week's raw items; headline must name the company; `PF_NOISE`
   drops stock tips and market lists; aliases of 4 chars or fewer match case-sensitively, so
   "Vi" is not "GTA VI"), `EWS` flags red / amber / green from the shown headline only.
   `Company.signal`: GigaCode's `ai_level` (red/amber/green/none) wins over the keyword flag.
   MCP prepare appends `portfolio_prompt()`; publish runs `apply_portfolio_notes()`. Live
   check with 10 public names: ED attachment = red, Q2 loss = amber, order wins = positive.

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
  Each run displays them and asks for updates (the user's request of 6 Nov 2026).
- **Six blocks of three items**, using the full page width, and the whole page on one
  1920 × 1080 screen without scrolling (the user's requests of 6 Nov 2026).
- No home-regulator feed: the user said not to add one.
- **AI first, local fallback**: the AI does the ranking and impact judgement; the keyword
  ranking is the fallback. AI stays optional (no key = keyword ranking).
- **GigaCode via MCP** is the in-house alternative to Gemini; the user asked that nothing
  but news goes to an external API.
- The free **Gemini** tier is the default because it costs nothing. Only public news plus
  `profile.bank` and `profile.guidance` from `sources.json` are sent; `cro_desk.txt` and
  `pending_items.txt` never are (`TestPrivacy` checks this).
- Links must be clickable in every format.
- The report (with CRO notes and pending items) is published to the user's Confluence page
  with history, one dated entry per run; the PAT stays in `Confluence PAT.txt` on their machine.
- **The India test** (11 Nov 2026, after a UK detention/sanctions story became the story of
  the week, which the user said is not worthy of the CRO's attention): `AI_SYSTEM` says impact
  means a direct effect on the bank's India operations; enforcement, court cases, arrests or
  detentions abroad and other countries' own banking news rate 4 or below unless the text
  shows a direct India effect, and are never the story of the week. The keyword fallback
  prefers a story matching `INDIA` for the story of the week. `cro_desk.txt` is not the place
  for such steering: it is never sent to the AI.
- The "foreign banks in India as a group" guidance line was added and then rolled back at
  the user's request (6 Nov 2026); `profile.guidance` is as before.

## Open items

- **First real AI-first run (6 Nov 2026):** `gemini-3.8-flash` answered 503 "high demand";
  `gemini-3.5-flash-lite` then ranked all 18 items well (every item had a "why it matters",
  so the old missing-"why" issue did not recur). The action point came back at ~50 words
  (asked for 35), so it is now kept up to 450 characters. Busy retries were added after this
  run; 3.8 Flash itself has still not answered a real request.
- Gemini free-tier limits are per project and shown only in Google AI Studio.
- Google News links are Google redirect addresses; they open fine in a browser.
- Possible next steps the user has not asked for yet: a weekly schedule, sending by email,
  a scraper for RBI's draft-directions page and CERT-In advisories (no feeds; see the source
  research of 6 Nov 2026), BIS feeds (supported by the parser, but mostly research).
- Free LLM research (6 Nov 2026): Gemini's free tier with `gemini-3.8-flash` is the best fit
  (free limits not published by Google; ~20 requests/day reported). Free-tier data may be used
  by Google and read by reviewers. Possible second provider if needed: SambaNova or Groq
  `gpt-oss-120b` (OpenAI-style API; Groq's free plan caps 8K tokens/min, the prompt is ~7.4K).
  Ruled out: GitHub Models (retired), Mistral (no free API), Cerebras (trial only), DeepSeek,
  Hugging Face. 3.8 Flash has not yet been run for real: check the first `--ai` run's
  `ai-reply.json` (`model` and `finishReason`).

- **Console encoding** (11 Nov 2026): the user's Windows console uses a non-UTF-8 code page
  (likely cp866, Russian locale), and printing "₹" raised UnicodeEncodeError, which also
  stopped Confluence publishing (it ran after the console print). `safe_console()` sets
  `errors="replace"` on stdout/stderr, and `main()` now publishes before printing.

## History

Built first inside `yogeshthakker/rbi-intel` (an RBI regulatory-intelligence project), then
moved here. `rbi-intel` no longer contains it; its branch `claude/ecstatic-meitner-vusea5`
holds only a Gemini default-model fix. `yogeshthakker/RiskLens2` was emptied and is unused.

## Conventions

- Run the tests before every commit, on Python 3.11 as well (no backslashes inside
  f-string expressions: the user's Python version is unknown). Keep the tool to one file and the standard library
  (python-pptx and anthropic optional).
- Check the slide visually after layout changes (LibreOffice can render it to PDF).
- Never commit `cro_desk.txt`, `pending_items.txt`, `top 20.txt`, `.env`, `Confluence PAT.txt` or `output/`.
