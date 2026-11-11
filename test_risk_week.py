import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import risk_week as rw  # noqa: E402

NOW = datetime(2026, 11, 5, 18, 0, tzinfo=rw.IST)


def source(name):
    return f'<source url="x">{name}</source>' if name else ""


def rss(*items):
    body = "".join(
        f"<item><title><![CDATA[{t}]]></title><link>{link}</link><description><![CDATA[{d}]]></description>"
        f"<pubDate>{date}</pubDate>{source(src)}</item>"
        for t, link, d, date, src in items
    )
    return f'﻿<?xml version="1.0"?><rss version="2.0"><channel>{body}</channel></rss>'.encode()


RBI = rss(
    ("Money Market Operations as on November 04, 2026", "https://rbi/1", "", "Thu, 05 Nov 2026 10:00:00", ""),
    ("RBI issues draft directions on expected credit loss provisioning for all commercial banks", "https://rbi/2",
     "The draft applies to all commercial banks with effect from April 1, 2027.", "Tue, 03 Nov 2026 17:00:00", ""),
    ("Directions under Section 35A read with Section 56 of the Banking Regulation Act, 1949 – The Pusad Urban "
     "Co-operative Bank Ltd., Pusad – Extension of Period", "https://rbi/3", "", "Wed, 04 Nov 2026 12:00:00", ""),
    ("RBI imposes monetary penalty on Alpha Finance Limited", "https://rbi/4", "", "Mon, 02 Nov 2026 12:00:00", ""),
)
SEBI = rss(
    ("SEBI Order for Compliance - Release Order for Recovery Certificate No. 1", "https://sebi/1", "", "04 Nov, 2026 +0530", ""),
)
NEWS = rss(
    ("Cyber attack disrupts UPI services at major private bank - Mint", "https://g/1", "", "Wed, 04 Nov 2026 08:00:00 GMT", "Mint"),
    ("Major private bank hit by cyber attack, UPI services disrupted - ET", "https://g/2", "", "Wed, 04 Nov 2026 09:00:00 GMT", "ET"),
    ("Bank NPA slippages surge in unsecured loans, microfinance stress persists - BS", "https://g/3", "", "Mon, 02 Nov 2026 09:00:00 GMT", "BS"),
    ("KYC lapses: FIU fines payments bank under PMLA - BL", "https://g/4", "", "Sun, 01 Nov 2026 09:00:00 GMT", "BL"),
    ("Gold price today rises; Sensex ends higher - X", "https://g/5", "", "Wed, 04 Nov 2026 09:00:00 GMT", "X"),
    ("2020 DHFL BANK FRAUD CASE: THE SCAM THAT SHOOK INDIA - Y", "https://g/6", "", "Wed, 04 Nov 2026 09:00:00 GMT", "Y"),
    ("Bank liquidity deficit widens as deposit growth lags credit - Z", "https://g/7", "", "Tue, 20 Oct 2026 09:00:00 GMT", "Z"),
)
SOURCES = {
    "feeds": [{"name": "RBI", "url": "rbi", "weight": 3, "primary": True},
              {"name": "SEBI", "url": "sebi", "weight": 1.5, "primary": True}],
    "google_news": {"weight": 1, "queries": ["bank risk"]},
}


def fetcher(url):
    if url == "rbi":
        return RBI
    if url == "sebi":
        return SEBI
    if url.startswith("https://news.google.com/"):
        assert "when%3A7d" in url
        return NEWS
    raise OSError("unreachable")


class FakeAI:
    name, model = "fake", "fake-1"

    def __init__(self, reply):
        self.reply = reply

    def json_call(self, system_prompt, user_content, response_schema=None, max_output_tokens=1200):
        self.prompt = getattr(self, "prompt", "") or user_content   # the first (pick) request
        self.system = system_prompt
        return self.reply


class TestParse(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(rw.parse_date("04 Nov, 2026 +0530").day, 4)
        self.assertEqual(rw.parse_date("Thu, 05 Nov 2026 12:45:00").tzinfo, rw.IST)
        self.assertIsNone(rw.parse_date("not a date"))

    def test_google_publisher_split(self):
        items = rw.parse_feed(NEWS, "g", google=True)
        self.assertEqual(items[0].title, "Cyber attack disrupts UPI services at major private bank")
        self.assertEqual(items[0].publisher, "Mint")


class TestRun(unittest.TestCase):
    def setUp(self):
        self.res = rw.run(days=7, top=3, sources=SOURCES, fetcher=fetcher, now=NOW)
        self.titles = [s.lead.title for s in self.res.top]

    def test_noise_and_out_of_period_dropped(self):
        everything = " ".join(s.lead.title for s in self.res.top + self.res.radar)
        for t in ("Money Market", "Recovery Certificate", "Gold price", "liquidity deficit"):
            self.assertNotIn(t, everything)

    def test_same_story_grouped(self):
        cyber = [s for s in self.res.top if "cyber" in s.lead.title.lower()]
        self.assertEqual(len(cyber), 1)
        self.assertEqual(cyber[0].sources, ["ET", "Mint"] if cyber[0].lead.publisher == "ET" else ["Mint", "ET"])

    def test_routine_enforcement_left_out_and_listed(self):
        ranked = " ".join(s.lead.title for s in self.res.top + self.res.radar)
        self.assertNotIn("Pusad", ranked)
        self.assertNotIn("Alpha Finance", ranked)
        listed = " ".join(i.title for i in self.res.routine)
        self.assertIn("Pusad", listed)
        self.assertIn("Alpha Finance", listed)

    def test_rbi_draft_leads_compliance_and_lookback_ranked_low(self):
        self.assertIn("expected credit loss", self.res.blocks["Compliance risk"][0].lead.title)   # a draft rule
        dhfl = [s for s in self.res.top if "DHFL" in s.lead.title]
        others = [s for s in self.res.top if "DHFL" not in s.lead.title]
        self.assertTrue(all(d.score < min(o.score for o in others) for d in dhfl))

    def test_six_blocks_in_order(self):
        self.assertEqual(list(self.res.blocks), ["Credit risk", "Market risk", "Non-financial risk",
                                                 "Cyber security risk", "Fraud risk", "Compliance risk"])
        self.assertTrue(all(len(v) <= 3 for v in self.res.blocks.values()))
        self.assertEqual(self.res.top, rw.flatten(self.res.blocks))
        cyber = self.res.blocks["Cyber security risk"][0].lead.title
        self.assertIn("Cyber attack", cyber + self.res.blocks["Cyber security risk"][0].items[-1].title)

    def test_one_bad_source_reported_not_fatal(self):
        src = dict(SOURCES, feeds=SOURCES["feeds"] + [{"name": "Broken", "url": "nope"}])
        res = rw.run(sources=src, fetcher=fetcher, now=NOW)
        self.assertTrue(res.top)
        self.assertTrue(res.errors[0].startswith("Broken:"))

    def test_outputs_written(self):
        with tempfile.TemporaryDirectory() as d:
            files = rw.write(self.res, d)
            md = pathlib.Path(files["markdown"]).read_text(encoding="utf-8")
            self.assertIn("This Week in Risk", md)
            self.assertIn("## Compliance risk\n\n### 1. [RBI issues draft directions", md)   # headline is the link
            self.assertIn("](https://rbi/2)", md)
            self.assertIn("Routine enforcement, not ranked (3)", md)
            page = pathlib.Path(files["html"]).read_text(encoding="utf-8")
            self.assertIn('href="https://rbi/2" target="_blank"', page)
            self.assertEqual(page.count('<section class="block">'), 6)
            self.assertIn("Nothing significant this week.", page)
            self.assertIn("<details>", page)
            try:
                from pptx import Presentation
            except ImportError:
                self.assertNotIn("pptx", files)
                return
            slide = Presentation(files["pptx"]).slides[1]          # slide 1: CRO's desk; slide 2: blocks
            links = [(r.text, r.hyperlink.address) for sh in slide.shapes if sh.has_text_frame
                     for para in sh.text_frame.paragraphs for r in para.runs if r.hyperlink.address]
            # the story of the week (here the RBI draft, the highest-impact item) is starred
            self.assertTrue(any(t.startswith("1. ★ RBI issues draft") and u == "https://rbi/2" for t, u in links))
            panels = [sh.text_frame.text.split("\n")[0] for sh in slide.shapes if sh.has_text_frame]
            for block in rw.BLOCKS:
                self.assertIn(block, panels)

    def test_console_has_plain_links(self):
        out = rw.to_console(self.res, {"html": "/tmp/x.html"})
        self.assertIn("\n   https://rbi/2\n", out)
        self.assertIn("file:///tmp/x.html", out)


PROFILE = rw.Profile.from_sources({"profile": {
    "focus": {"weight": 1.6, "terms": ["\\bfema\\b", "liquidity"]},
    "less_relevant": {"weight": 2.2, "terms": ["co-?operative", "farmer|drought"]},
    "foreign_banks": ["HSBC", "Standard Chartered"],
    "penalty_threshold_crore": 10,
}})


def item(title, summary=""):
    return rw.Item(title=title, link="l", source="s", published=NOW, summary=summary)


class TestProfile(unittest.TestCase):
    def test_amounts(self):
        self.assertEqual(rw.amount_crore("RBI imposes ₹1.57 crore penalty"), 1.57)
        self.assertEqual(rw.amount_crore("fine of Rs 50 lakh"), 0.5)
        self.assertEqual(rw.amount_crore("Rs 2,500 crore and ₹3 crore"), 2500)
        self.assertIsNone(rw.amount_crore("RBI imposes penalty on bank"))

    def test_routine_or_not(self):
        routine = lambda t: rw.is_routine_enforcement(item(t), PROFILE)  # noqa: E731
        self.assertTrue(routine("RBI imposes ₹1.57 crore penalty on Punjab National Bank"))
        self.assertTrue(routine("RBI imposes monetary penalty on XYZ Co-operative Bank"))
        self.assertFalse(routine("RBI imposes ₹25 crore penalty on large private bank"))       # big
        self.assertFalse(routine("RBI fines HSBC India ₹2 crore for KYC lapses"))              # peer
        self.assertFalse(routine("RBI bars fintech bank from onboarding new customers, penalty"))  # restriction
        self.assertFalse(routine("RBI issues draft liquidity framework for banks"))            # not enforcement

    def test_relevance_moves_scores(self):
        fema = rw.relevance(item("RBI amends FEMA rules for liquidity facility"), PROFILE)
        coop = rw.relevance(item("Drought hit farmers get co-operative bank relief"), PROFILE)
        peer = rw.relevance(item("Standard Chartered India sells unit"), PROFILE)
        self.assertGreater(fema, 0)
        self.assertLess(coop, 0)
        self.assertGreater(peer, 0)

    def test_profile_reaches_ai_prompt(self):
        ai = FakeAI({"items": []})
        src = dict(SOURCES, profile={"bank": "TestBank India branch"})
        rw.run(top=3, sources=src, fetcher=fetcher, now=NOW, provider=ai)
        self.assertIn("TestBank India branch", ai.prompt)
        self.assertIn("TestBank India branch", ai.system)

    def test_shipped_profile_is_valid(self):
        p = rw.Profile.from_sources(rw.load_sources())
        self.assertTrue(p.focus and p.less and p.peers)
        self.assertTrue(rw.is_routine_enforcement(item("RBI imposes ₹2.5 lakh penalty on Canara Bank"), p))


class TestStrictSchema(unittest.TestCase):
    def test_every_object_closed(self):
        s = rw._strict(rw.AI_SCHEMA)
        self.assertFalse(s["additionalProperties"])
        self.assertFalse(s["properties"]["items"]["items"]["additionalProperties"])
        self.assertNotIn("additionalProperties", rw.AI_SCHEMA)   # original left alone


class TestAI(unittest.TestCase):
    def test_ai_picks_and_phrases(self):
        ai = FakeAI({"items": [
            {"id": 2, "headline": "Cyber attack hits UPI", "category": "Operational, cyber & fraud",
             "why_it_matters": "Tests our own incident response."},
            {"id": 99, "headline": "invented", "category": "Capital", "why_it_matters": "x"},
        ]})
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=ai)
        self.assertIn("[1]", ai.prompt)
        picked = [s for s in res.top if s.headline == "Cyber attack hits UPI"]
        self.assertEqual(len(picked), 1)
        self.assertIn(picked[0].category, rw.BLOCKS)              # unknown block name: keyword block kept
        self.assertEqual(res.blocks[picked[0].category], picked)  # the AI's pick only, in its block
        self.assertNotIn("invented", rw.to_markdown(res))         # unknown id ignored
        self.assertIn("fake (fake-1)", res.ai)

    def test_unusable_reply_falls_back(self):
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=FakeAI({"answer": "x"}))
        self.assertIn("keyword ranking used", res.ai)
        plain = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW)
        self.assertEqual([s.lead.link for s in res.top], [s.lead.link for s in plain.top])


class TestAiFirst(unittest.TestCase):
    """With a provider, the AI ranks; the keyword ranking is only the fallback."""

    def stories_in_prompt(self, prompt):
        return {int(line[1:line.index("]")]): line for line in prompt.splitlines() if line.startswith("[")}

    def test_ai_orders_by_impact_and_picks_radar(self):
        probe = FakeAI({"items": []})
        rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=probe)
        lines = self.stories_in_prompt(probe.prompt)
        self.assertNotIn("Credit risk;", probe.prompt)            # no keyword block or score is shown
        ids = {k: v for k, v in lines.items()}
        npa = next(k for k, v in ids.items() if "NPA" in v)
        ecl = next(k for k, v in ids.items() if "expected credit loss" in v)
        cyber = next(k for k, v in ids.items() if "cyber" in v.lower())
        dhfl = next(k for k, v in ids.items() if "DHFL" in v)
        ai = FakeAI({"items": [
            {"id": npa, "category": "Credit risk", "impact": 4, "headline": "NPA", "why_it_matters": "a"},
            {"id": ecl, "category": "Credit risk", "impact": 9, "headline": "ECL", "why_it_matters": "b"},
        ], "radar": [cyber, ecl, 999], "cro_focus": {"id": ecl, "message": "Act."}})
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=ai)
        self.assertEqual([s.headline for s in res.blocks["Credit risk"]], ["ECL", "NPA"])   # by impact
        self.assertEqual(res.blocks["Credit risk"][0].impact, 9)
        self.assertEqual(res.blocks["Compliance risk"], [])       # the AI's judgement: nothing there
        self.assertEqual(res.blocks["Fraud risk"], [])            # the DHFL look-back is not shown
        self.assertEqual([s.lead.title for s in res.radar], [lines[cyber].split(") ", 1)[1]])
        self.assertEqual(res.cro_focus.story.headline, "ECL")
        self.assertIn("Impact 9/10", rw.to_markdown(res))
        self.assertIn('<span class="imp">Impact 9/10</span>', rw.to_html(res))
        self.assertTrue(dhfl)

    def test_rejected_reply_leaves_stories_untouched(self):
        ai = FakeAI({"items": [{"id": 1, "category": "Not a block", "impact": 9, "headline": "X",
                                "why_it_matters": "y"}]})
        ai2 = FakeAI({"items": [{"id": 999, "category": "Credit risk", "impact": 9, "headline": "X"}]})
        plain = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW)
        for fake in (ai2,):
            res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=fake)
            self.assertIn("keyword ranking used", res.ai)
            self.assertEqual([(s.lead.link, s.headline, s.impact) for s in res.top],
                             [(s.lead.link, s.headline, s.impact) for s in plain.top])
        self.assertTrue(ai)

    def test_india_test_in_prompt(self):
        ai = FakeAI({"items": []})
        rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=ai)
        self.assertIn("The India test", ai.system)
        self.assertIn("detentions abroad", ai.system)
        self.assertIn("passing the India test", ai.prompt)

    def test_fallback_story_of_week_prefers_india(self):
        news = rss(("UK court upholds detention of banker in sanctions case, warns banks", "https://g/uk", "",
                    "Wed, 04 Nov 2026 08:00:00 GMT", "FT"),
                   ("Indian banks see MSME loan demand rise", "https://g/in", "", "Tue, 03 Nov 2026 08:00:00 GMT", "M"))
        src = {"feeds": [], "google_news": {"queries": ["x"]}}
        res = rw.run(top=3, sources=src, fetcher=lambda u: news, now=NOW)
        self.assertEqual(res.cro_focus.story.lead.link, "https://g/in")

    def test_no_ai_says_keywords(self):
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW)
        self.assertEqual(res.ai, "keywords (AI off)")
        self.assertTrue(all(s.impact is None for s in res.top))


class TestSameStory(unittest.TestCase):
    """The second grouping pass, on one week's real headlines (test_headlines.json, 6 Nov 2026)."""

    @classmethod
    def setUpClass(cls):
        titles = json.loads((pathlib.Path(__file__).resolve().parent / "test_headlines.json")
                            .read_text(encoding="utf-8"))
        stories = []
        for n, title in enumerate(titles):
            it = rw.Item(title=title, link=f"https://x/{n}", source=f"S{n}", published=NOW)
            stories.append(rw.Story(items=[it], category="Credit risk", score=100 - n * 0.1))
        cls.before = len(stories)
        cls.merged = rw.merge_same_story(stories)

    def story_of(self, words):
        found = [s for s in self.merged if any(words in it.title for it in s.items)]
        self.assertEqual(len(found), 1, words)
        return {it.title for it in found[0].items}

    def test_fewer_stories(self):
        self.assertLess(len(self.merged), self.before)
        self.assertEqual(sum(len(s.items) for s in self.merged), self.before)   # nothing lost

    def test_same_story_in_different_words_is_merged(self):
        hedging = self.story_of("RBI crackdown on rupee bets")
        self.assertIn("RBI’s rupee-speculation curbs push corporate hedging lower", hedging)
        self.assertIn("India’s Dollar Hedging Slumps as RBI Cracks Down on Speculation", hedging)
        cert = self.story_of("CERT-In issues critical alert")
        self.assertGreaterEqual(len([t for t in cert if "CERT-In" in t or "I4C" in t]), 3)
        self.assertIn("US Sanctions Chandigarh Couple Over Alleged Iran Shipping Fraud",
                      self.story_of("US sanctions Indian couple behind fake flag"))

    def test_different_stories_stay_apart(self):
        self.assertNotIn("Bank of England makes first rate hike since 2023",
                         self.story_of("Riksbank delivers first rate hike"))
        self.assertNotIn("RBI Sets Up A New Market Committee", self.story_of("Govt sets up banking committee"))
        self.assertFalse(any("A7" in t for t in self.story_of("Razorpay gets final licence")))

    def test_small_sets_left_alone(self):
        few = [rw.Story(items=[rw.Item(title=t, link=t, source="s", published=NOW)], category="x", score=1)
               for t in ("CERT-In warns banks of AI attacks", "CERT-In alert on AI attacks on banks")]
        self.assertEqual(len(rw.merge_same_story(few)), 2)


class FakeConfluence:
    """Answers the two REST calls the client makes, and remembers the page."""

    def __init__(self, body="", version=7, conflicts=0):
        self.body, self.version, self.conflicts = body, version, conflicts
        self.calls = []

    def __call__(self, method, url, body, headers):
        self.calls.append((method, url, headers, json.loads(body) if body else None))
        if method == "GET":
            return json.dumps({"id": "123", "title": "This Week in Risk", "version": {"number": self.version},
                               "body": {"storage": {"value": self.body}}}).encode()
        if self.conflicts:
            self.conflicts -= 1
            raise urllib.error.HTTPError(url, 409, "Conflict", {}, io.BytesIO(b"stale"))
        data = json.loads(body)
        self.body, self.version = data["body"]["storage"]["value"], data["version"]["number"]
        return b"{}"


class TestConfluence(unittest.TestCase):
    CFG = {"CONFLUENCE_BASE_URL": "https://confluence.example.com/", "PAGE_ID": "123", "PAT": "sekret-pat",
           "VERIFY_SSL": False, "CONFLUENCE_TIMEOUT": 60}

    def setUp(self):
        self.res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, cro_notes=["Board RAS 20 Nov"],
                          pending=[rw.Pending(item="Old & late", owner="Risk", due="01 Nov 2026", status="Open",
                                              overdue=True)])

    def client(self, fake):
        return rw.ConfluenceClient(self.CFG, opener=fake)

    def test_reads_the_settings_file_format(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "Confluence PAT.txt"
            f.write_text('# ----\n# A.4 Confluence Configuration\n# ----\n'
                         'CONFLUENCE_BASE_URL = "https://confluence.example.com"\nPAGE_ID = "20268286076"\n'
                         'PAT = "abc#123"\nVERIFY_SSL = False           # development only\n'
                         'CONFLUENCE_TIMEOUT = 60\n', encoding="utf-8")
            cfg = rw.load_confluence_config(f)
        self.assertEqual(cfg["CONFLUENCE_BASE_URL"], "https://confluence.example.com")
        self.assertEqual(cfg["PAGE_ID"], "20268286076")
        self.assertEqual(cfg["PAT"], "abc#123")                    # '#' inside quotes is kept
        self.assertIs(cfg["VERIFY_SSL"], False)
        self.assertEqual(cfg["CONFLUENCE_TIMEOUT"], 60)
        self.assertIsNone(rw.load_confluence_config(pathlib.Path("/no/such/file.txt")))

    def test_week_is_valid_confluence_storage(self):
        week = rw.to_confluence(self.res)
        import xml.etree.ElementTree as ET
        ET.fromstring('<r xmlns:ac="http://atlassian.com/content" xmlns:ri="http://atlassian.com/resource">'
                      + rw.build_confluence_body("", week, "2026-W45") + "</r>")     # well-formed XML
        self.assertIn('ac:name="info"', week)
        self.assertIn("For CRO&#x27;s desk", week)
        self.assertIn("Old &amp; late", week)
        self.assertIn('<ac:parameter ac:name="colour">Red</ac:parameter>', week)   # overdue
        self.assertIn("<th>Credit risk</th>", week)
        self.assertIn('href="https://rbi/2"', week)

    def test_publish_updates_the_page_with_history(self):
        fake = FakeConfluence()
        msg = rw.publish_confluence(self.res, self.CFG, client=self.client(fake))
        method, url, headers, data = fake.calls[-1]
        self.assertEqual(method, "PUT")
        self.assertEqual(url, "https://confluence.example.com/rest/api/content/123")
        self.assertEqual(headers["Authorization"], "Bearer sekret-pat")
        self.assertEqual(data["version"]["number"], 8)
        self.assertEqual(data["title"], "This Week in Risk")
        self.assertNotIn("sekret-pat", msg)
        self.assertIn("2026-W45", msg)
        # next week: last week moves under "Previous weeks"; the same week again is replaced
        later = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW + rw.timedelta(days=7))
        rw.publish_confluence(later, self.CFG, client=self.client(fake))
        rw.publish_confluence(later, self.CFG, client=self.client(fake))
        weeks = rw._weeks_on_page(fake.body)
        self.assertEqual(sorted(weeks), ["2026-W45", "2026-W46"])
        self.assertLess(fake.body.index("rtw-week-2026-W46"), fake.body.index("<h2>Previous weeks</h2>"))
        self.assertIn('<ac:parameter ac:name="title">This Week in Risk — week ending 05 Nov 2026</ac:parameter>',
                      fake.body)
        self.assertEqual(fake.version, 10)

    def test_keep_limits_weeks_on_page(self):
        body = ""
        for n in range(5):
            res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW + rw.timedelta(days=7 * n))
            body = rw.build_confluence_body(body, rw.to_confluence(res), rw._week_key(res), keep=3)
        self.assertEqual(sorted(rw._weeks_on_page(body)), ["2026-W47", "2026-W48", "2026-W49"])

    def test_conflict_is_retried_once(self):
        fake = FakeConfluence(conflicts=1)
        rw.publish_confluence(self.res, self.CFG, client=self.client(fake))
        self.assertEqual([c[0] for c in fake.calls], ["GET", "PUT", "GET", "PUT"])

    def test_missing_pat_and_dry_run(self):
        self.assertIn("PAT missing", rw.publish_confluence(self.res, dict(self.CFG, PAT="")))
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "page.xml"
            msg = rw.publish_confluence(self.res, {}, dry_run_file=f)
            self.assertIn("nothing uploaded", msg)
            self.assertIn("rtw-week-2026-W45", f.read_text(encoding="utf-8"))

    def test_check_reads_only(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "c.txt"
            f.write_text('CONFLUENCE_BASE_URL = "https://c.example.com"\nPAGE_ID = "123"\nPAT = "x"\n', encoding="utf-8")
            fake = FakeConfluence(version=3)
            with mock.patch.object(rw.ConfluenceClient, "_open", lambda self, *args: fake(*args)):
                out = rw.confluence_check(type("A", (), {"confluence_config": str(f)})())
        self.assertIn("OK. News page (published to): 'This Week in Risk' (id 123), version 3", out)
        self.assertEqual([c[0] for c in fake.calls], ["GET"])

    def test_refuses_a_page_with_other_content(self):
        fake = FakeConfluence(body="<h1>ISE 2025</h1><table><tr><td>Observation 1: KYC refresh pending for "
                                   "accounts flagged in the inspection</td></tr></table>")
        msg = rw.publish_confluence(self.res, self.CFG, client=self.client(fake))
        self.assertIn("not published", msg)
        self.assertIn("content not written by this tool", msg)
        self.assertEqual([c[0] for c in fake.calls], ["GET"])     # nothing written
        msg = rw.publish_confluence(self.res, self.CFG, client=self.client(fake), allow_replace=True)
        self.assertIn("published", msg)
        self.assertEqual(fake.calls[-1][0], "PUT")

    def test_own_page_and_empty_page_are_fine(self):
        fake = FakeConfluence(body="<p></p>")
        rw.publish_confluence(self.res, self.CFG, client=self.client(fake))
        self.assertEqual(rw.foreign_content(fake.body), "")
        later = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW + rw.timedelta(days=7))
        self.assertIn("published", rw.publish_confluence(later, self.CFG, client=self.client(fake)))
        self.assertEqual(rw.foreign_content(fake.body), "")       # two weeks, still all ours

    def test_purpose_named_page_keys(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "c.txt"
            f.write_text('CONFLUENCE_BASE_URL = "https://c.example.com"\nNEWS_PAGE_ID = "111"\n'
                         'ISE_PAGE_ID = "19000597275"\nPAT = "x"\n', encoding="utf-8")
            cfg = rw.load_confluence_config(f)
        self.assertEqual((cfg["PAGE_ID"], cfg["COMPLIANCE_PAGE_ID"]), ("111", "19000597275"))
        self.assertNotIn("_DUPLICATES", cfg)
        self.assertEqual(rw.publish_problems(cfg), [])
        example = rw.load_confluence_config(pathlib.Path(__file__).resolve().parent / "confluence.example.txt")
        self.assertEqual(example["PAGE_ID"], "123456789")

    def test_refuses_duplicate_settings_and_the_compliance_page(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "c.txt"
            f.write_text('CONFLUENCE_BASE_URL = "https://c.example.com"\nPAGE_ID = "111"\nPAT = "x"\n'
                         'PAGE_ID = "222"\n', encoding="utf-8")
            cfg = rw.load_confluence_config(f)
        self.assertEqual(cfg["_DUPLICATES"], ["PAGE_ID"])
        fake = FakeConfluence()
        self.assertIn("more than once", rw.publish_confluence(self.res, cfg, client=self.client(fake)))
        same = dict(self.CFG, COMPLIANCE_PAGE_ID="123")
        self.assertIn("RBI compliance page", rw.publish_confluence(self.res, same, client=self.client(fake)))
        self.assertEqual(fake.calls, [])                          # refused before any request

    def test_http_errors_explained(self):
        def denied(method, url, body, headers):
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b""))
        with self.assertRaises(RuntimeError) as c:
            rw.publish_confluence(self.res, self.CFG, client=self.client(denied))
        self.assertIn("PAT was not accepted", str(c.exception))
        self.assertNotIn("sekret-pat", str(c.exception))


COMPLIANCE_PAGE = (
    '<p>Status of RBI observations</p>'
    '<table><tbody>'
    '<tr><th>Sub-section</th><th>Observation</th><th>CBS / Non-CBS</th><th>Department</th>'
    '<th>Head of Department</th><th>Comments received from departments</th><th>Official deadline</th>'
    '<th><p>Compliant/Non-Compliant&nbsp; submitted to RBI (15.04.2026)</p></th></tr>'
    '<tr><td rowspan="2"><p>KYC</p></td><td><p>Periodic KYC update overdue for 120 accounts</p></td><td>CBS</td>'
    '<td>Operations</td><td>A. Sharma</td><td>Remediation in progress</td><td>30.10.2026</td>'
    '<td><ac:structured-macro ac:name="status"><ac:parameter ac:name="colour">Red</ac:parameter>'
    '<ac:parameter ac:name="title">Non-Compliant</ac:parameter></ac:structured-macro></td></tr>'
    '<tr><td>Beneficial owner &amp; UBO records incomplete</td><td>Non-CBS</td><td>Compliance</td><td>B. Rao</td>'
    '<td></td><td>15.12.2026</td><td></td></tr>'
    '<tr><td>Outsourcing</td><td>Vendor risk assessments not refreshed</td><td>Non-CBS</td><td>IT</td>'
    '<td>C. Iyer</td><td>Done</td><td>15.04.2026</td><td>Compliant</td></tr>'
    '</tbody></table>'
    '<table><tbody><tr><th>Unrelated</th><th>Table</th></tr><tr><td>x</td><td>y</td></tr></tbody></table>'
)


class TestCompliance(unittest.TestCase):
    TODAY = datetime(2026, 11, 11).date()

    def test_reads_the_rbi_compliance_table(self):
        items = rw.parse_compliance(COMPLIANCE_PAGE, self.TODAY)
        self.assertEqual(len(items), 3)                            # the unrelated table is ignored
        kyc, ubo, vendor = items
        self.assertEqual(kyc.subsection, "KYC")
        self.assertEqual(ubo.subsection, "KYC")                    # merged cell filled down
        self.assertEqual(ubo.observation, "Beneficial owner & UBO records incomplete")
        self.assertEqual(kyc.status, "Non-Compliant")              # the label's title, not its colour
        self.assertEqual(kyc.owner, "Operations (A. Sharma)")
        self.assertEqual(kyc.cbs, "CBS")
        self.assertEqual(kyc.comments, "Remediation in progress")
        self.assertEqual(kyc.due_date, datetime(2026, 10, 30).date())
        self.assertTrue(kyc.overdue and not kyc.done)              # 'Non-Compliant' is not done
        self.assertFalse(ubo.overdue or ubo.done)
        self.assertTrue(vendor.done and not vendor.overdue)
        self.assertEqual([i.observation[:8] for i in rw.open_compliance(items)], ["Periodic", "Benefici"])
        self.assertEqual(kyc.shown_status, "Overdue (Non-Compliant)")
        self.assertEqual(ubo.shown_status, "Open")

    def test_load_reads_the_page_and_reports_problems(self):
        fake = FakeConfluence(body=COMPLIANCE_PAGE)
        cfg = dict(TestConfluence.CFG, COMPLIANCE_PAGE_ID="999")
        items, info = rw.load_compliance(cfg, client=rw.ConfluenceClient(cfg, opener=fake), today=self.TODAY)
        self.assertIn("/rest/api/content/999?", fake.calls[0][1])
        self.assertEqual([c[0] for c in fake.calls], ["GET"])      # read only
        self.assertEqual((len(items), info["total"], info["closed"], info["overdue"]), (2, 3, 1, 1))
        self.assertTrue(info["url"].endswith("pageId=999"))
        self.assertEqual(rw.load_compliance({}, today=self.TODAY), ([], {}))      # not configured: nothing
        def down(method, url, body, headers):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
        items, info = rw.load_compliance(cfg, client=rw.ConfluenceClient(cfg, opener=down))
        self.assertEqual(items, [])
        self.assertIn("HTTP 404", info["error"])
        items, info = rw.load_compliance(cfg, client=rw.ConfluenceClient(cfg, opener=FakeConfluence(body="<p>x</p>")))
        self.assertIn("no table", info["error"])

    def test_shown_in_every_format(self):
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW)
        cfg = dict(TestConfluence.CFG, COMPLIANCE_PAGE_ID="999")
        res.compliance, res.compliance_info = rw.load_compliance(
            cfg, client=rw.ConfluenceClient(cfg, opener=FakeConfluence(body=COMPLIANCE_PAGE)), today=self.TODAY)
        self.assertIn("## Pending RBI compliance items", rw.to_markdown(res))
        self.assertIn("**Overdue (Non-Compliant)**", rw.to_markdown(res))
        page = rw.to_html(res)
        self.assertIn("Pending RBI compliance", page)
        self.assertIn('title="Comments: Remediation in progress"', page)
        self.assertIn("pageId=999", page)
        self.assertIn("PENDING RBI COMPLIANCE (2 open, 1 overdue, of 3)", rw.to_console(res, {}))
        week = rw.to_confluence(res)
        self.assertIn("Pending RBI compliance items", week)
        import xml.etree.ElementTree as ET
        ET.fromstring('<r xmlns:ac="a" xmlns:ri="b">' + week + "</r>")
        try:
            from pptx import Presentation
        except ImportError:
            return
        with tempfile.TemporaryDirectory() as d:
            files = rw.write(res, d)
            titles = [[sh.text_frame.text for sh in sl.shapes if sh.has_text_frame][0]
                      for sl in Presentation(files["pptx"]).slides]
        self.assertIn("Pending RBI compliance items", "\n".join(titles))


class TestPrivacy(unittest.TestCase):
    def test_notes_and_pending_never_sent_to_ai(self):
        sent = []

        class Spy:
            name, model = "spy", "spy-1"

            def json_call(self, system_prompt, user_content, response_schema=None, max_output_tokens=0):
                sent.append(system_prompt + user_content)
                return {"items": [{"id": 1, "category": "Credit risk", "impact": 5, "headline": "H",
                                   "why_it_matters": ""}], "radar": [], "cro_focus": {"id": 1, "message": "m"}}

        pend = [rw.Pending(item="SECRET-PENDING-ITEM", owner="SECRET-OWNER")]
        rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=Spy(),
               cro_notes=["SECRET-CRO-NOTE"], pending=pend)
        self.assertEqual(len(sent), 2)                             # rank, then fill_why
        for text in sent:
            for secret in ("SECRET-PENDING-ITEM", "SECRET-OWNER", "SECRET-CRO-NOTE"):
                self.assertNotIn(secret, text)


class SeqAI:
    """Answers each request with the next reply in the list."""
    name, model = "seq", "seq-1"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def json_call(self, system_prompt, user_content, response_schema=None, max_output_tokens=1200):
        self.prompts.append(user_content)
        return self.replies.pop(0) if self.replies else {}


class TestSummariesAndCro(unittest.TestCase):
    def pick(self, items, focus=None):
        return {"items": items, "cro_focus": focus or {"id": 1, "message": "Ask Treasury to size it."}}

    def test_missing_why_filled_by_second_request(self):
        ai = SeqAI(
            self.pick([{"id": 1, "headline": "A", "category": "Capital", "why_it_matters": ""},
                       {"id": 2, "headline": "B", "category": "Capital", "why_it_matters": " "},
                       {"id": 3, "headline": "C", "category": "Capital", "why_it_matters": "Has one."}]),
            {"items": [{"id": n, "why_it_matters": f"Filled {n}."} for n in range(1, 30)]},
        )
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=ai)
        whys = [s.why for s in res.top]
        self.assertTrue(all(whys))
        self.assertIn("Has one.", whys)                           # an AI line is kept, not asked again
        self.assertEqual(len(ai.prompts), 2)
        kept = next(s for s in res.top if s.why == "Has one.")
        self.assertNotIn(kept.lead.title, ai.prompts[1])          # only the missing ones are asked again
        self.assertEqual([e["request"] for e in res.ai_log], ["rank", "fill_why"])

    def test_other_key_names_accepted(self):
        ai = SeqAI(self.pick([{"id": 1, "headline": "A", "category": "Capital", "why": "Via 'why'."}]))
        res = rw.run(top=1, sources=SOURCES, fetcher=fetcher, now=NOW, provider=ai)
        self.assertIn("Via 'why'.", [s.why for s in res.top])

    def test_cro_focus_from_ai(self):
        ai = SeqAI(self.pick([{"id": 1, "headline": "A", "category": "Capital", "why_it_matters": "x"},
                              {"id": 2, "headline": "B", "category": "Capital", "why_it_matters": "y"}],
                             {"id": 2, "message": "Ask Credit to check exposure."}))
        res = rw.run(top=2, sources=SOURCES, fetcher=fetcher, now=NOW, provider=ai,
                     cro_notes=["RAS review to Board on 20 Nov"])
        box = rw.cro_box(res)
        self.assertEqual(box["notes"], ["RAS review to Board on 20 Nov"])
        self.assertEqual(box["focus"]["headline"], "B")
        self.assertEqual(box["focus"]["action"], "Ask Credit to check exposure.")
        self.assertEqual(box["focus"]["why"], "y")
        self.assertIn("cro_focus", ai.prompts[0])

    def test_story_of_week_without_ai_is_highest_impact(self):
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW)
        self.assertIs(res.cro_focus.story, max(res.top, key=lambda s: s.score))
        self.assertIsNotNone(rw.cro_box(res))

    def test_cro_box_in_every_format(self):
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, cro_notes=["Board RAS review 20 Nov"],
                     provider=SeqAI(self.pick([{"id": 1, "headline": "A", "category": "Capital",
                                                "why_it_matters": "x"}])))
        with tempfile.TemporaryDirectory() as d:
            files = rw.write(res, d)
            md = pathlib.Path(files["markdown"]).read_text(encoding="utf-8")
            self.assertIn("> ### For CRO's desk", md)
            self.assertIn("> - Board RAS review 20 Nov", md)
            self.assertIn("> **Story of the week** (", md)
            self.assertIn("> **Action point:** Ask Treasury to size it.", md)
            self.assertIn('<span class="star">★ Story of the week</span>',
                          pathlib.Path(files["html"]).read_text(encoding="utf-8"))
            page = pathlib.Path(files["html"]).read_text(encoding="utf-8")
            self.assertIn('<section class="panel cro">', page)
            self.assertIn("Board RAS review 20 Nov", page)
            self.assertIn('"request": "rank"', pathlib.Path(files["ai_reply"]).read_text(encoding="utf-8"))
            self.assertIn("FOR CRO'S DESK", rw.to_console(res, files))
            try:
                from pptx import Presentation
            except ImportError:
                return
            texts = [sh.text_frame.text for sh in Presentation(files["pptx"]).slides[0].shapes
                     if sh.has_text_frame]
            panel = [x for x in texts if x.startswith("For CRO's desk")]
            self.assertEqual(len(panel), 1)
            self.assertIn("Board RAS review 20 Nov", panel[0])
            self.assertIn("Story of the week", panel[0])
            self.assertIn("Action point", panel[0])

    def test_notes_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "cro_desk.txt"
            f.write_text("# comment\n\n- First note\nSecond note\n• Third\n", encoding="utf-8")
            self.assertEqual(rw.load_cro_notes(f), ["First note", "Second note", "Third"])
            self.assertEqual(rw.load_cro_notes(pathlib.Path(d) / "missing.txt"), [])

    def test_example_notes_file_parses(self):
        notes = rw.load_cro_notes(pathlib.Path(__file__).resolve().parent / "cro_desk.example.txt")
        self.assertEqual(len(notes), 2)



class TestFeedFormats(unittest.TestCase):
    def test_gzip_bare_ampersand_and_rss1(self):
        import gzip
        amp = (b'<?xml version="1.0"?><rss><channel><item><title>Margins for FX & IRS segment</title>'
               b'<link>https://ccil/1</link><pubDate>Thu, 05 Nov 2026 10:00:00</pubDate></item></channel></rss>')
        self.assertEqual(rw.parse_feed(gzip.compress(amp), "CCIL")[0].title, "Margins for FX & IRS segment")
        rdf = (b'<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
               b'xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">'
               b'<channel><title>BIS</title></channel><item><title>Basel speech</title><link>https://bis/1</link>'
               b'<dc:date>2026-11-04T10:00:00Z</dc:date></item></rdf:RDF>')
        got = rw.parse_feed(rdf, "BIS")
        self.assertEqual((got[0].title, got[0].link), ("Basel speech", "https://bis/1"))
        self.assertEqual(got[0].published.day, 4)


class TestPriorities(unittest.TestCase):
    def test_msme_and_russia_outrank_other_focus(self):
        prof = rw.Profile.from_sources(rw.load_sources())
        msme = rw.relevance(item("RBI widens credit guarantee cover for MSME loans"), prof)
        russia = rw.relevance(item("Indian banks halt payments for Russian oil after sanctions"), prof)
        other = rw.relevance(item("RBI amends FEMA rules for liquidity facility"), prof)
        self.assertGreater(msme, other)
        self.assertGreater(russia, other)
        self.assertEqual(rw.categorise(item("Banks step up MSME lending via TReDS"))[0], "Credit risk")

    def test_priority_topic_gets_a_slot(self):
        news = rss(*[(f"RBI tightens cyber security norms for banks, round {n}", f"https://g/c{n}",
                      "", "Wed, 04 Nov 2026 08:00:00 GMT", f"P{n}") for n in range(3)],
                   ("Bank of Baroda sees MSME loan demand rise", "https://g/m", "", "Tue, 03 Nov 2026 08:00:00 GMT", "M"),
                   ("NPA slippages and asset quality stress rise in bank loans", "https://g/npa", "",
                    "Wed, 04 Nov 2026 08:00:00 GMT", "N"))
        src = {"feeds": [{"name": "RBI", "url": "rbi", "weight": 3, "primary": True}],
               "google_news": {"queries": ["x"]},
               "profile": {"priority": {"weight": 0, "topics": {"MSME lending": ["\\bmsmes?\\b"]}}}}
        f = lambda u: RBI if u == "rbi" else news
        res = rw.run(top=1, sources=src, fetcher=f, now=NOW)       # one place in Credit: NPA story or MSME
        self.assertIn("https://g/m", [s.lead.link for s in res.top])
        no = rw.run(top=1, sources=dict(src, profile={}), fetcher=f, now=NOW)
        self.assertNotIn("https://g/m", [s.lead.link for s in no.top])

    def test_guidance_reaches_ai(self):
        ai = FakeAI({"items": []})
        src = dict(SOURCES, profile={"guidance": "MSME lending first"})
        rw.run(top=3, sources=src, fetcher=fetcher, now=NOW, provider=ai)
        self.assertIn("MSME lending first", ai.system)


class TestPending(unittest.TestCase):
    TODAY = datetime(2026, 11, 6).date()

    def load(self, text):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "pending_items.txt"
            f.write_text(text, encoding="utf-8")
            return rw.load_pending(f, self.TODAY)

    def test_parse_order_and_overdue(self):
        got = self.load("# comment\n\nLater | A | 20 Nov 2026 | Open\n"
                        "Closed one | B | 01 Nov 2026 | Done\nLate one | C | 2026-11-02 | In progress\n"
                        "- No details\n")
        self.assertEqual([p.item for p in got], ["Late one", "Later", "No details", "Closed one"])
        self.assertTrue(got[0].overdue)
        self.assertFalse(got[3].overdue)
        self.assertEqual(rw._status(got[0]), "Overdue (In progress)")
        self.assertEqual(rw._status(got[2]), "Open")
        self.assertEqual(rw.load_pending(pathlib.Path("/no/such/file"), self.TODAY), [])

    def review(self, text, answers):
        out = []
        answers = iter(answers)
        d = tempfile.mkdtemp()
        f = pathlib.Path(d) / "pending_items.txt"
        if text is not None:
            f.write_text(text, encoding="utf-8")
        items = rw.review_pending(f, ask=lambda prompt: next(answers), say=out.append, today=self.TODAY)
        return items, f, "\n".join(out)

    def test_review_shows_items_and_enter_changes_nothing(self):
        text = "# my header\nBoard paper | CRO office | 20 Nov 2026 | Open\n"
        items, f, shown = self.review(text, [""])
        self.assertIn("1. Board paper · CRO office · 20 Nov 2026 · Open", shown)
        self.assertEqual(f.read_text(encoding="utf-8"), text)          # untouched
        self.assertEqual([p.item for p in items], ["Board paper"])

    def test_review_edit_done_add_delete_and_save(self):
        text = "# my header\nBoard paper | CRO office | 20 Nov 2026 | Open\nOld item | X | | Open\n"
        items, f, shown = self.review(text, [
            "1", "", "Risk team", "31 Feb 2026", "02 Nov 2026", "",    # edit 1: owner, a bad date, then a good one
            "a", "MSME scorecard", "Credit", "15 Nov 2026", "",         # add (status defaults to Open)
            "x 3",                                                     # delete "Old item" (third after sorting)
            "huh",                                                     # not understood: nothing changes
            "",                                                        # carry on
        ])
        self.assertIn("Could not read that date", shown)
        self.assertIn("Not understood", shown)
        self.assertIn("Saved", shown)
        saved = f.read_text(encoding="utf-8")
        self.assertTrue(saved.startswith("# my header\n"))              # comments kept
        self.assertIn("Board paper | Risk team | 02 Nov 2026 | Open", saved)
        self.assertIn("MSME scorecard | Credit | 15 Nov 2026 | Open", saved)
        self.assertNotIn("Old item", saved)
        self.assertEqual(items[0].item, "Board paper")                 # now overdue: first
        self.assertTrue(items[0].overdue)
        again = rw.load_pending(f, self.TODAY)
        self.assertEqual([p.item for p in again], [p.item for p in items])

    def test_review_mark_done_and_new_file(self):
        items, f, shown = self.review(None, ["a", "First item", "", "", "", "d 1", ""])
        self.assertIn("none yet", shown)
        self.assertEqual(items[0].status, "Done")
        saved = f.read_text(encoding="utf-8")
        self.assertTrue(saved.startswith("# Pending items for the weekly status meeting"))
        self.assertIn("First item |  |  | Done", saved)

    def test_example_file_parses(self):
        got = rw.load_pending(pathlib.Path(__file__).resolve().parent / "pending_items.example.txt", self.TODAY)
        self.assertEqual(len(got), 4)

    def test_pending_in_every_format(self):
        pend = self.load("Board RAS paper | CRO office | 01 Nov 2026 | Open\nMSME policy | Credit | 20 Nov 2026 |\n")
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, pending=pend)
        with tempfile.TemporaryDirectory() as d:
            files = rw.write(res, d)
            md = pathlib.Path(files["markdown"]).read_text(encoding="utf-8")
            self.assertIn("## Pending items", md)
            self.assertIn("| Board RAS paper | CRO office | 01 Nov 2026 | **Overdue (Open)** |", md)
            self.assertIn('class="late"', pathlib.Path(files["html"]).read_text(encoding="utf-8"))
            self.assertIn("PENDING ITEMS", rw.to_console(res, files))
            try:
                from pptx import Presentation
            except ImportError:
                return
            slide = Presentation(files["pptx"]).slides[0]           # next to the CRO's desk
            tables = [sh.table for sh in slide.shapes if sh.has_table]
            self.assertEqual(len(tables), 1)
            self.assertEqual(tables[0].cell(1, 0).text, "Board RAS paper")
            self.assertEqual(tables[0].cell(1, 3).text, "Overdue (Open)")

def gemini_reply(obj):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}, "finishReason": "STOP"}]}


class TestGemini(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}, clear=False)
        self.env.start()
        os.environ.pop("RISK_WEEK_MODEL", None)

    def tearDown(self):
        self.env.stop()

    def test_request_shape_and_answer(self):
        calls = []

        def post(url, body, headers):
            calls.append((url, body, headers))
            return gemini_reply({"items": [{"id": 1, "headline": "H", "category": "Capital",
                                            "why_it_matters": "W"}]})

        g = rw.GeminiProvider(post=post)
        self.assertEqual(g.model, "gemini-3.8-flash")
        out = g.json_call("sys", "user", rw.AI_SCHEMA)
        self.assertEqual(out["items"][0]["headline"], "H")
        url, body, headers = calls[0]
        self.assertIn("/models/gemini-3.8-flash:generateContent", url)
        self.assertNotIn("temperature", body["generationConfig"])            # ignored by Gemini 3.6+
        self.assertGreaterEqual(body["generationConfig"]["maxOutputTokens"], 16384)   # includes thinking
        self.assertEqual(headers, {"x-goog-api-key": "k"})
        self.assertNotIn("k", url)                                   # key in a header, not the URL
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(body["generationConfig"]["responseJsonSchema"], rw.AI_SCHEMA)
        self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "sys")

    def test_used_by_run(self):
        post = lambda url, body, headers: gemini_reply({"items": [  # noqa: E731
            {"id": 1, "headline": "Gemini headline", "category": "Credit risk", "why_it_matters": "W"}]})
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=rw.GeminiProvider(post=post))
        self.assertEqual(res.top[0].headline, "Gemini headline")
        self.assertIn("gemini (gemini-3.8-flash)", res.ai)

    def test_daily_limit_falls_back_to_keywords(self):
        def post(url, body, headers):
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, io.BytesIO(b"quota"))

        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=rw.GeminiProvider(post=post))
        self.assertIn("keyword ranking used", res.ai)
        self.assertTrue(res.top)

    def test_falls_back_to_flash_lite(self):
        urls = []

        def post(url, body, headers):
            urls.append(url)
            if "gemini-3.8-flash:" in url:
                raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, io.BytesIO(b"quota"))
            return gemini_reply({"items": [{"id": 1, "headline": "Lite", "category": "Credit risk",
                                            "impact": 7, "why_it_matters": "W"}], "radar": [],
                                 "cro_focus": {"id": 1, "message": "m"}})

        waits = []
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW,
                     provider=rw.GeminiProvider(post=post, sleep=waits.append))
        self.assertEqual(waits, [])                                # a daily limit is not retried
        self.assertIn("/models/gemini-3.8-flash:", urls[0])
        self.assertIn("/models/gemini-3.5-flash-lite:", urls[1])
        self.assertIn("gemini-3.5-flash-lite, after gemini-3.8-flash: free-tier limit", res.ai)
        self.assertIn("Lite", [s.headline for s in res.top])

    def test_busy_model_retried_before_fallback(self):
        calls, waits = [], []

        def post(url, body, headers):
            calls.append(url)
            if len(calls) < 3:                                    # busy twice, then answers
                raise urllib.error.HTTPError(url, 503, "Unavailable", {}, io.BytesIO(b"high demand"))
            return gemini_reply({"items": [{"id": 1, "headline": "Flash", "category": "Credit risk",
                                            "impact": 8, "why_it_matters": "W"}], "radar": [],
                                 "cro_focus": {"id": 1, "message": "m"}})

        g = rw.GeminiProvider(post=post, sleep=waits.append)
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=g)
        self.assertTrue(all("gemini-3.8-flash:" in u for u in calls))   # no fallback needed
        self.assertEqual(waits, [10, 30])
        self.assertIn("gemini-3.8-flash on try 3", res.ai)

    def test_busy_three_times_then_flash_lite(self):
        calls, waits = [], []

        def post(url, body, headers):
            calls.append(url)
            if "gemini-3.8-flash:" in url:
                raise urllib.error.HTTPError(url, 503, "Unavailable", {}, io.BytesIO(b"high demand"))
            return gemini_reply({"items": [{"id": 1, "headline": "Lite", "category": "Credit risk",
                                            "impact": 8, "why_it_matters": "W"}], "radar": [],
                                 "cro_focus": {"id": 1, "message": "m"}})

        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW,
                     provider=rw.GeminiProvider(post=post, sleep=waits.append))
        self.assertEqual(sum("gemini-3.8-flash:" in u for u in calls), 3)
        self.assertIn("gemini-3.5-flash-lite, after gemini-3.8-flash: HTTP 503", res.ai)
        self.assertIn("tried 3 times", res.ai)

    def test_cut_off_reply_tries_fallback_then_keywords(self):
        cut = {"candidates": [{"content": {"parts": [{"text": '{"items": [{"id": 1'}]},
                               "finishReason": "MAX_TOKENS"}]}
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW,
                     provider=rw.GeminiProvider(post=lambda url, body, headers: cut))
        self.assertIn("cut off", res.ai)
        self.assertIn("gemini-3.5-flash-lite", res.ai)
        self.assertIn("keyword ranking used", res.ai)

    def test_fenced_json_and_thoughts_tolerated(self):
        post = lambda url, body, headers: {"candidates": [{"content": {"parts": [  # noqa: E731
            {"text": "thinking...", "thought": True}, {"text": '```json\n{"items": []}\n```'}]}}]}
        self.assertEqual(rw.GeminiProvider(post=post).json_call("s", "u"), {"items": []})

    def test_missing_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                rw.GeminiProvider()

    def test_dotenv_does_not_override(self):
        with tempfile.TemporaryDirectory() as d:
            env = pathlib.Path(d) / ".env"
            env.write_text("# key\nexport RW_TEST_A='one'\nGEMINI_API_KEY=from-file\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "real"}):
                rw.load_dotenv(env, pathlib.Path(d) / "missing")
                self.assertEqual(os.environ["RW_TEST_A"], "one")
                self.assertEqual(os.environ["GEMINI_API_KEY"], "real")
            os.environ.pop("RW_TEST_A", None)


if __name__ == "__main__":
    unittest.main()
