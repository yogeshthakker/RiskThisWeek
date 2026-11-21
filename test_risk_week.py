import io
import json
import re
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
        # resolve() gives /tmp/... on Unix and C:/tmp/... on Windows; the URI must follow either
        self.assertIn(pathlib.Path("/tmp/x.html").resolve().as_uri(), out)


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
            {"id": npa, "category": "Credit risk", "impact": 6, "headline": "NPA", "why_it_matters": "a"},
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

    def test_longer_why_requested_and_kept(self):
        ai = FakeAI({"items": []})
        rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=ai)
        self.assertIn("two or three sentences (at most 55 words)", ai.prompt)
        self.assertIn("what to check, prepare or act on", ai.prompt)
        long_why = " ".join(["word"] * 55)                        # ~280 characters
        self.assertEqual(rw._why({"why_it_matters": long_why}), long_why)

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
        self.assertIn("Report of 05 Nov 2026, 18:00, 1 report(s)", msg)
        # every run is its own entry, even later the same day; the same minute again replaces it
        later = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW + rw.timedelta(hours=2))
        rw.publish_confluence(later, self.CFG, client=self.client(fake))
        rw.publish_confluence(later, self.CFG, client=self.client(fake))
        entries = rw._weeks_on_page(fake.body)
        self.assertEqual(sorted(entries), ["20261105T1800", "20261105T2000"])
        self.assertLess(fake.body.index("rtw-week-20261105T2000"), fake.body.index("<h2>Previous reports</h2>"))
        self.assertIn('<ac:parameter ac:name="title">Report of 05 Nov 2026, 18:00</ac:parameter>', fake.body)
        self.assertEqual(fake.version, 10)
        self.assertEqual(rw.foreign_content(fake.body), "")       # still all ours: publishing allowed

    def test_old_weekly_entry_is_kept_below_new_runs(self):
        old_res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW - rw.timedelta(days=1))
        old = rw.to_confluence(old_res).replace(rw._week_key(old_res), "2026-W45")    # as written before
        body = rw.build_confluence_body("", old, "2026-W45")
        body = body.replace("Updated by risk_week.py on every run. The latest report is first; earlier reports "
                            "are below, newest first.", "Updated each week by risk_week.py. The latest week is "
                            "first; earlier weeks are below, newest first.")
        self.assertEqual(rw.foreign_content(body), "")           # the old intro is recognised as ours
        fake = FakeConfluence(body=body)
        rw.publish_confluence(self.res, self.CFG, client=self.client(fake))
        later = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW + rw.timedelta(days=7))
        rw.publish_confluence(later, self.CFG, client=self.client(fake))
        order = [k for k in sorted(rw._weeks_on_page(fake.body), key=rw._entry_order, reverse=True)]
        self.assertEqual(order, ["20261112T1800", "20261105T1800", "2026-W45"])
        self.assertTrue(fake.body.index("rtw-week-20261112T1800") < fake.body.index("rtw-week-20261105T1800")
                        < fake.body.index("rtw-week-2026-W45"))

    def test_keep_limits_weeks_on_page(self):
        body = ""
        for n in range(5):
            res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW + rw.timedelta(days=7 * n))
            body = rw.build_confluence_body(body, rw.to_confluence(res), rw._week_key(res), keep=3)
        self.assertEqual(sorted(rw._weeks_on_page(body)), ["20261119T1800", "20261126T1800", "20261203T1800"])

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
            self.assertIn("rtw-week-20261105T1800", f.read_text(encoding="utf-8"))

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
    '<tr><td>Beneficial owner &amp; UBO records incomplete</td><td>Non-CBS</td><td>Credit Risk</td><td>B. Rao</td>'
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

    def test_rmp_items(self):
        page = COMPLIANCE_PAGE.replace("<td>15.12.2026</td>", "<td>RMP</td>")
        items = rw.parse_compliance(page, self.TODAY)
        ubo = items[1]
        self.assertTrue(ubo.rmp and ubo.severe and not ubo.overdue)
        self.assertEqual(ubo.shown_status, "RMP: deadline per mitigation plan")
        self.assertEqual([i.observation[:8] for i in rw.open_compliance(items)], ["Benefici", "Periodic"])  # RMP first
        self.assertEqual(rw._ise_counts(rw.open_compliance(items)), "2 open, 1 on RMP, 1 overdue")
        cfg = dict(TestConfluence.CFG, COMPLIANCE_PAGE_ID="999", ISE_DEPARTMENT="")
        _, info = rw.load_compliance(cfg, client=rw.ConfluenceClient(cfg, opener=FakeConfluence(body=page)),
                                     today=self.TODAY)
        self.assertEqual((info["rmp"], info["unread_deadlines"]), (1, 0))     # not "not understood"
        self.assertTrue(rw._RMP.search("As per Risk Mitigation Plan"))
        self.assertFalse(rw._RMP.search("RMPL vendor"))

    def test_department_filter(self):
        cfg = dict(TestConfluence.CFG, COMPLIANCE_PAGE_ID="999")
        load = lambda c: rw.load_compliance(c, client=rw.ConfluenceClient(c, opener=FakeConfluence(body=COMPLIANCE_PAGE)),
                                            today=self.TODAY)  # noqa: E731
        items, info = load(cfg)                                   # default: department contains "risk"
        self.assertEqual([i.department for i in items], ["Credit Risk"])
        self.assertEqual((info["page_total"], info["total"], info["department"]), (3, 1, "risk"))
        items, info = load(dict(cfg, ISE_DEPARTMENT=""))          # every department
        self.assertEqual(len(items), 2)
        items, info = load(dict(cfg, ISE_DEPARTMENT="Treasury"))
        self.assertEqual(items, [])
        self.assertIn("no rows with department 'Treasury'", info["error"])
        self.assertIn("Credit Risk", info["error"])               # lists what is there
        self.assertFalse(re.search(r"(?<![a-z])risk(?![a-z])", "asterisk"))   # whole word only

    def test_deadline_formats(self):
        d = lambda y, m, day: datetime(y, m, day).date()  # noqa: E731
        cases = {"15.04.2026": d(2026, 4, 15), "15/04/26": d(2026, 4, 15), "2026-04-15": d(2026, 4, 15),
                 "15 April 2026": d(2026, 4, 15), "15th Apr'26": d(2026, 4, 15), "31st March, 2026": d(2026, 3, 31),
                 "April 15, 2026": d(2026, 4, 15), "Sept 2026": d(2026, 9, 30), "Feb'28": d(2028, 2, 29),
                 "March 2026 (revised to 30.06.2026)": d(2026, 6, 30), "15-Apr-2026": d(2026, 4, 15),
                 "30 Septemebr 2026": d(2026, 9, 30), "Septemebr 2026": d(2026, 9, 30), "Augst'26": d(2026, 8, 31),
                 "Decmber 15, 2026": d(2026, 12, 15)}
        for text, want in cases.items():
            self.assertEqual(rw._first_date(text), want, text)
        for text in ("Immediate", "Q1 FY27", "", "31.02.2026", "RMP"):
            self.assertIsNone(rw._first_date(text), text)

    def test_check_reports_unread_deadlines(self):
        page = COMPLIANCE_PAGE.replace("<td>15.12.2026</td>", "<td>Immediate</td>")
        cfg = dict(TestConfluence.CFG, COMPLIANCE_PAGE_ID="999")
        items, info = rw.load_compliance(cfg, client=rw.ConfluenceClient(cfg, opener=FakeConfluence(body=page)),
                                         today=self.TODAY)
        self.assertEqual((info["unread_deadlines"], info["unread_examples"]), (1, ["Immediate"]))

    def test_load_reads_the_page_and_reports_problems(self):
        fake = FakeConfluence(body=COMPLIANCE_PAGE)
        cfg = dict(TestConfluence.CFG, COMPLIANCE_PAGE_ID="999", ISE_DEPARTMENT="")
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

    def test_confluence_order_news_first_compliance_last(self):
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, cro_notes=["note"],
                     pending=[rw.Pending(item="P1")])
        cfg = dict(TestConfluence.CFG, COMPLIANCE_PAGE_ID="999", ISE_DEPARTMENT="")
        res.compliance, res.compliance_info = rw.load_compliance(
            cfg, client=rw.ConfluenceClient(cfg, opener=FakeConfluence(body=COMPLIANCE_PAGE)), today=self.TODAY)
        week = rw.to_confluence(res)
        order = [week.index(x) for x in ('ac:name="info"', "<h3>This week by risk area</h3>",
                                         "Routine enforcement, not ranked", "<h3>Pending items</h3>",
                                         "<h3>Pending RBI compliance items", "rtw-end-")]
        self.assertEqual(order, sorted(order))

    def test_shown_in_every_format(self):
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW)
        cfg = dict(TestConfluence.CFG, COMPLIANCE_PAGE_ID="999", ISE_DEPARTMENT="")
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


class TestConsole(unittest.TestCase):
    def test_rupee_sign_in_a_russian_or_western_console(self):
        for codepage in ("cp866", "cp1251", "cp1252"):
            raw = io.BytesIO()
            stream = io.TextIOWrapper(raw, encoding=codepage)
            with self.assertRaises(UnicodeEncodeError):
                stream.write("₹10 crore – ‘ok’")
                stream.flush()
            stream = io.TextIOWrapper(io.BytesIO(), encoding=codepage)
            rw.safe_console(stream)
            stream.write("SBI projects ₹19,500 crore impact – RBI’s view\n")   # no error now
            stream.flush()
            self.assertIn(b"19,500 crore", stream.buffer.getvalue())

    def test_whole_console_summary_prints_in_cp866(self):
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, cro_notes=["Board ₹ paper – draft"])
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp866")
        rw.safe_console(stream)
        stream.write(rw.to_console(res, {"html": "/tmp/x.html"}))
        stream.flush()


class TestMcp(unittest.TestCase):
    """GigaCode (an MCP client) ranks the news; everything else stays on this computer."""

    def server(self, d):
        base = pathlib.Path(d)
        (base / "cro_desk.txt").write_text("SECRET-CRO-NOTE\n", encoding="utf-8")
        (base / "pending_items.txt").write_text("SECRET-PENDING | Risk | 30 Nov 2026 | Open\n", encoding="utf-8")
        return rw.McpServer(fetcher=fetcher, sources=SOURCES, now=NOW, out_dir=base / "out", base_dir=base)

    def call(self, srv, name, args=None, mid=1):
        r = srv.handle({"jsonrpc": "2.0", "id": mid, "method": "tools/call",
                        "params": {"name": name, "arguments": args or {}}})
        return r["result"]["content"][0]["text"], r["result"]["isError"]

    def test_protocol_basics(self):
        srv = rw.McpServer()
        init = srv.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                           "params": {"protocolVersion": "2025-03-26", "capabilities": {}}})
        self.assertEqual(init["result"]["protocolVersion"], "2025-03-26")
        self.assertIn("tools", init["result"]["capabilities"])
        self.assertIsNone(srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        names = [t["name"] for t in srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]]
        self.assertEqual(names, ["risk_week_prepare", "risk_week_candidates", "risk_week_publish", "risk_week_run",
                                 "risk_week_check"])
        self.assertEqual(srv.handle({"jsonrpc": "2.0", "id": 2, "method": "nope"})["error"]["code"], -32601)

    def test_candidates_come_in_pages(self):
        with tempfile.TemporaryDirectory() as d:
            srv = self.server(d)
            text, err = self.call(srv, "risk_week_prepare", {"page_size": 2})
            batch = text.split("Batch: ")[1].split("\n")[0]
            total = len(srv.pool)
            pages = -(-total // 2)
            self.assertGreater(pages, 1)
            self.assertIn(f"come in {pages} pages", text)
            self.assertIn(f"Page 1 of {pages} · ids 1–2 of {total}", text)
            self.assertTrue(text.rstrip().endswith(f"page 2.)"))      # the end says what to do next
            self.assertNotIn("[3]", text)
            p2, err = self.call(srv, "risk_week_candidates", {"batch": batch, "page": 2})
            self.assertFalse(err)
            self.assertIn("[3]", p2)
            self.assertNotIn("[2]", p2)
            last, _ = self.call(srv, "risk_week_candidates", {"batch": batch, "page": pages})
            self.assertIn("that was the last page", last)
            self.assertTrue(self.call(srv, "risk_week_candidates", {"batch": batch, "page": pages + 1})[1])
            self.assertTrue(self.call(srv, "risk_week_candidates", {"batch": "nope", "page": 2})[1])
            # a new server process still serves the saved pages
            srv2 = rw.McpServer(fetcher=fetcher, sources=SOURCES, now=NOW, out_dir=pathlib.Path(d) / "out",
                                base_dir=pathlib.Path(d))
            self.assertEqual(self.call(srv2, "risk_week_candidates", {"batch": batch, "page": 2})[0], p2)

    def test_prepare_rank_publish(self):
        with tempfile.TemporaryDirectory() as d:
            srv = self.server(d)
            text, err = self.call(srv, "risk_week_publish", {"batch": "x", "ranking": {}})
            self.assertTrue(err)                                  # prepare first
            self.assertIn("not the current candidate list", text)
            text, err = self.call(srv, "risk_week_prepare")
            batch = text.split("Batch: ")[1].split("\n")[0]
            self.assertFalse(err)
            self.assertIn("The India test", text)                 # the same instructions as for Gemini
            self.assertIn("Answer format for `ranking`", text)
            for secret in ("SECRET-CRO-NOTE", "SECRET-PENDING"):
                self.assertNotIn(secret, text)                    # local notes never go to the client
            lines = {int(l[1:l.index("]")]): l for l in text.split("Candidates:\n")[1].splitlines() if l.startswith("[")}
            ecl = next(k for k, v in lines.items() if "expected credit loss" in v)
            bad, err = self.call(srv, "risk_week_publish", {"batch": batch, "ranking": {"items": [{"id": 999}]}})
            self.assertTrue(err)
            self.assertIn("could not be used", bad)
            ranking = {"items": [{"id": ecl, "category": "Credit risk", "impact": 9, "headline": "ECL draft",
                                  "why_it_matters": "Provisioning changes for us."}],
                       "radar": [], "cro_focus": {"id": ecl, "message": "Ask Finance to size the ECL impact."}}
            self.assertIn("Pass `batch`", self.call(srv, "risk_week_publish", {"ranking": ranking})[0])
            # a new server process (as when a script restarts it) still publishes the saved batch
            srv = rw.McpServer(fetcher=fetcher, sources=SOURCES, now=NOW, out_dir=pathlib.Path(d) / "out",
                               base_dir=pathlib.Path(d))
            text, err = self.call(srv, "risk_week_publish", {"batch": batch, "ranking": json.dumps(ranking),
                                                             "publish": False})
            self.assertFalse(err)
            self.assertIn("Ranked by: AI · GigaCode via MCP", text)
            self.assertIn("story of the week: ECL draft", text)
            self.assertIn("not published (publish = false)", text)
            for secret in ("SECRET-CRO-NOTE", "SECRET-PENDING"):
                self.assertNotIn(secret, text)                    # nor in the reply to the client
            out = pathlib.Path(d) / "out"
            md = next(out.glob("*.md")).read_text(encoding="utf-8")
            self.assertIn("Ask Finance to size the ECL impact.", md)
            self.assertIn("SECRET-CRO-NOTE", md)                  # notes and pending items are in the report
            self.assertIn("SECRET-PENDING", md)
            self.assertTrue(self.call(srv, "risk_week_publish", {"batch": batch, "ranking": ranking})[1])  # once

    def test_run_with_gemini_or_keywords(self):
        with tempfile.TemporaryDirectory() as d:
            srv = self.server(d)
            seen = []

            class FakeGemini:
                name, model, label = "gemini", "gemini-3.8-flash", "gemini-3.8-flash"
                def json_call(self, system, user, response_schema=None, max_output_tokens=0):
                    seen.append(user)
                    first = int(user.split("Candidates:\n")[1].splitlines()[0][1:].split("]")[0])
                    return {"items": [{"id": first, "category": "Credit risk", "impact": 8, "headline": "G pick",
                                       "why_it_matters": "w"}], "radar": [], "cro_focus": {"id": first, "message": "m"}}

            srv.gemini = FakeGemini
            text, err = self.call(srv, "risk_week_run", {"publish": False})          # default: gemini
            self.assertFalse(err)
            self.assertIn("Ranked by: AI · gemini (gemini-3.8-flash", text)
            self.assertIn("story of the week: G pick", text)
            self.assertIn("not published (publish = false)", text)
            for secret in ("SECRET-CRO-NOTE", "SECRET-PENDING"):
                self.assertNotIn(secret, text)
                self.assertNotIn(secret, seen[0])                 # nor sent to Gemini
            text, err = self.call(srv, "risk_week_run", {"ranker": "keywords", "publish": False})
            self.assertIn("Ranked by: keywords (AI off)", text)
            def no_key():
                raise RuntimeError("set GEMINI_API_KEY")
            srv.gemini = no_key
            text, err = self.call(srv, "risk_week_run", {"publish": False})
            self.assertFalse(err)
            self.assertIn("keywords (Gemini unavailable: set GEMINI_API_KEY)", text)
            self.assertTrue(self.call(srv, "risk_week_run", {"ranker": "gpt"})[1])

    def test_shifted_ids_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            srv = self.server(d)
            text, _ = self.call(srv, "risk_week_prepare")
            batch = text.split("Batch: ")[1].split("\n")[0]
            lines = {int(l[1:l.index("]")]): l.split(") ", 1)[1] for l in text.split("Candidates:\n")[1].splitlines()
                     if l.startswith("[")}
            n = len(lines)
            # every headline is right, but each id points one story further on
            shifted = {"items": [{"id": k % n + 1, "category": "Credit risk", "impact": 7,
                                  "headline": lines[k][:60], "why_it_matters": "x"} for k in lines],
                       "radar": [], "cro_focus": {"id": 1, "message": "m"}}
            text, err = self.call(srv, "risk_week_publish", {"batch": batch, "ranking": shifted})
            self.assertTrue(err)
            self.assertIn("do not match the candidates", text)
            right = dict(shifted, items=[dict(i, id=k) for k, i in zip(lines, shifted["items"])])
            self.assertEqual(rw.ranking_mismatches(srv.pool, right), [])
            # a second prepare replaces the batch: the old code is refused
            self.call(srv, "risk_week_prepare")
            srv2 = rw.McpServer(out_dir=pathlib.Path(d) / "out", base_dir=pathlib.Path(d))
            self.assertIn("not the current candidate list",
                          self.call(srv2, "risk_week_publish", {"batch": "deadbeef", "ranking": right})[0])

    def test_stdout_carries_only_protocol(self):
        import subprocess
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "ping"}]
        p = subprocess.run([sys.executable, str(pathlib.Path(rw.__file__)), "--mcp"],
                           input="".join(json.dumps(m) + "\n" for m in msgs).encode(),
                           capture_output=True, timeout=60)
        lines = p.stdout.decode("utf-8").splitlines()
        self.assertEqual([json.loads(l)["id"] for l in lines], [1, 2, 3])


class TestSafetyNet(unittest.TestCase):
    """After any AI ranking, the user's rules apply whatever the model picked."""

    NEWS = rss(
        ("Supersession of Board of Directors of Abhyudaya Co-operative Bank Ltd., Mumbai", "https://g/coop",
         "", "Wed, 04 Nov 2026 08:00:00 GMT", "RBI"),
        ("Indian sailor detained in UK for transporting sanctioned Russian oil", "https://g/sailor", "",
         "Wed, 04 Nov 2026 09:00:00 GMT", "BBC"),
        ("Supreme Court tells banks to pay victims of cyber fraud", "https://g/sc", "",
         "Tue, 03 Nov 2026 09:00:00 GMT", "LiveLaw"),
        ("RBI extends Mudra loan guarantee for MSME borrowers", "https://g/mudra", "",
         "Tue, 03 Nov 2026 10:00:00 GMT", "ET"),
        ("RBI tightens cyber security norms for payment operators", "https://g/cyber", "",
         "Mon, 02 Nov 2026 10:00:00 GMT", "Mint"),
        ("Russian fintech A7 plans rupee cross-border payments in India", "https://g/a7", "",
         "Mon, 02 Nov 2026 11:00:00 GMT", "ET"))
    SRC = {"feeds": [], "google_news": {"queries": ["x"]}, "profile": json.loads(
        (pathlib.Path(__file__).resolve().parent / "sources.json").read_text(encoding="utf-8"))["profile"]}

    def run_with(self, reply):
        class AI:
            name, model = "fake", "f"
            def json_call(s, system, user, response_schema=None, max_output_tokens=0):
                self.prompt = user
                return reply(user) if callable(reply) else {"items": []}
        return rw.run(top=3, sources=self.SRC, fetcher=lambda u: self.NEWS, now=NOW, provider=AI())

    def test_rules_override_the_ai(self):
        def reply(user):
            ids = {l.split(") ", 1)[1][:12]: int(l[1:l.index("]")]) for l in user.split("Candidates:\n")[1].splitlines()
                   if l.startswith("[")}
            i = lambda prefix: next(v for k, v in ids.items() if k.startswith(prefix))  # noqa: E731
            pick = lambda pre, block, imp: {"id": i(pre), "category": block, "impact": imp,  # noqa: E731
                                            "headline": pre, "why_it_matters": "w"}
            return {"items": [pick("Supersession", "Non-financial risk", 7),
                              pick("Indian sailo", "Compliance risk", 9),
                              pick("Russian fint", "Compliance risk", 8),
                              pick("Supreme Cour", "Fraud risk", 8),
                              pick("RBI extends ", "Credit risk", 8)],
                    "radar": [], "cro_focus": {"id": i("Indian sailo"), "message": "Raise sanctions screening."}}
        res = self.run_with(reply)
        links = [s.lead.link for s in res.top]
        self.assertNotIn("https://g/coop", links)                 # pass-over list
        self.assertNotIn("https://g/sailor", links)               # detention abroad
        self.assertIn("https://g/sc", links)                      # an Indian court stays
        self.assertIn("https://g/a7", links)
        self.assertEqual(res.cro_focus.story.lead.link, "https://g/mudra")    # highest remaining India pick
        self.assertEqual(res.cro_focus.message, "")               # the action point was for the old story
        self.assertIn("safety net: 3 change(s)", res.ai)
        notes = next(e["safety_net"] for e in res.ai_log if "safety_net" in e)
        self.assertTrue(any("pass-over" in n for n in notes) and any("abroad" in n for n in notes))
        self.assertEqual(res.blocks["Non-financial risk"], [])    # nothing left that passes: stays empty

    def test_good_ranking_is_untouched(self):
        def reply(user):
            first = next(int(l[1:l.index("]")]) for l in user.split("Candidates:\n")[1].splitlines()
                         if l.startswith("[") and "Mudra" in l)
            return {"items": [{"id": first, "category": "Credit risk", "impact": 8, "headline": "Mudra",
                               "why_it_matters": "w"}], "radar": [], "cro_focus": {"id": first, "message": "Act."}}
        res = self.run_with(reply)
        self.assertNotIn("safety net", res.ai)
        self.assertEqual(res.cro_focus.message, "Act.")
        self.assertEqual([s.lead.link for s in res.top], ["https://g/mudra"])   # the AI's one pick, no top-up

    def test_relevant_headline_kept_despite_pass_over_words(self):
        week = rw.prepare_week(sources=self.SRC, fetcher=lambda u: rss(
            ("More trouble for Page Industries after weak Q2 results: RBI returns FEMA compounding application",
             "https://g/fema", "", "Wed, 04 Nov 2026 08:00:00 GMT", "ET")), now=NOW)
        st = week.stories[0]
        st.impact, st.category = 7, "Compliance risk"
        pick = rw.AiPick(blocks={b: ([st] if b == "Compliance risk" else []) for b in rw.BLOCKS},
                         focus=rw.CroFocus(st, "m"))
        out, notes = rw.apply_rules(pick, week, 3)
        self.assertEqual(notes, [])
        self.assertEqual(out.blocks["Compliance risk"], [st])

    def test_low_impact_dropped_not_replaced(self):
        def reply(user):
            ids = {l.split(") ", 1)[1][:12]: int(l[1:l.index("]")]) for l in user.split("Candidates:\n")[1].splitlines()
                   if l.startswith("[")}
            i = lambda prefix: next(v for k, v in ids.items() if k.startswith(prefix))  # noqa: E731
            return {"items": [{"id": i("RBI extends "), "category": "Credit risk", "impact": 8, "headline": "Mudra",
                               "why_it_matters": "w"},
                              {"id": i("RBI tightens"), "category": "Cyber security risk", "impact": 4,
                               "headline": "Cyber", "why_it_matters": "w"},
                              {"id": i("Russian fint"), "category": "Compliance risk", "impact": 5,
                               "headline": "A7", "why_it_matters": "w"}],
                    "radar": [], "cro_focus": {"id": i("RBI tightens"), "message": "m"}}
        res = self.run_with(reply)
        self.assertEqual([s.headline for s in res.top], ["Mudra", "A7"])         # 4/10 gone, 5/10 kept
        self.assertEqual(res.blocks["Cyber security risk"], [])                # and not refilled
        self.assertEqual(res.cro_focus.story.headline, "Mudra")                 # focus moved off it
        notes = next(e["safety_net"] for e in res.ai_log if "safety_net" in e)
        self.assertTrue(any("impact 4/10" in n for n in notes))

    def test_patterns(self):
        excl = rw.Profile.from_sources(self.SRC).exclude
        for t in ("Abhyudaya Co-op Bank board superseded", "Urban co-operative bank licence cancelled",
                  "Microfinance stress rises", "HDFC Bank Q2 results: net profit up"):
            self.assertTrue(excl.search(t), t)
        for t in ("RBI widens MSME credit guarantee", "Cooperation pact on cyber security", "Bond yields rise"):
            self.assertFalse(excl.search(t), t)


RBI_DRAFTS_PAGE = (
    '<table class="tablebg"><tr><td class="tableheader" colspan="2"><b>Nov 05, 2026</b></td></tr>'
    "<tr><td><a class='link2' href=BS_PressReleaseDisplay.aspx?prid=1>Priority Sector Lending – Drafts for Comments</a></td></tr>"
    '<tr><td class="tableheader" colspan="2"><b>Oct 20, 2026</b></td></tr>'
    "<tr><td><a class='link2' href=BS_PressReleaseDisplay.aspx?prid=2>Draft KYC Amendment Directions</a></td></tr>"
    '<tr><td class="tableheader" colspan="2"><b>Jan 10, 2026</b></td></tr>'
    "<tr><td><a class='link2' href=BS_PressReleaseDisplay.aspx?prid=3>An old draft</a></td></tr></table>")
CAFRAL_LIST = ('<a href="/events/ecl-board-oversight-programme">ECL</a> <a href="/events/learning">Learning</a>'
               '<a href="/events/kyc-aml-senior-executives-programme">KYC</a>')


def cafral_page(start, end, title, place):
    return (f'<var class="atc_date_start">{start} 09:45:00</var><var class="atc_date_end">{end} 17:00:00</var>'
            f'<var class="atc_title">{title}</var><var class="atc_location">{place}</var>')


EVENT_PAGES = {
    rw.RBI_DRAFTS: RBI_DRAFTS_PAGE,
    "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=1":
        "<p>Comments may be submitted on or before November 26, 2026.</p>",
    "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=2":
        "<p>Comments were invited by October 31, 2026.</p>",
    rw.CAFRAL_EVENTS: CAFRAL_LIST,
    "https://www.cafral.org.in/events/ecl-board-oversight-programme":
        cafral_page("2026-11-25", "2026-11-25", "ECL Framework: Board Oversight Programme",
                    "CAFRAL Campus, Dadar (West), Mumbai – 400028"),
    "https://www.cafral.org.in/events/kyc-aml-senior-executives-programme":
        cafral_page("2026-12-03", "2026-12-04", "Programme on KYC/AML for Senior Executives", "Mumbai"),
}
REPORTS = rss(("BIS: liquidity stress testing for banks", "https://bis/1", "", "Wed, 11 Nov 2026 08:00:00 GMT", ""),
              ("Cyber attack disrupts UPI services at major private bank", "https://bis/2", "",
               "Tue, 10 Nov 2026 08:00:00 GMT", ""),
              ("1 | Page Consultation paper on anti-money laundering norms", "https://bis/3", "",
               "Tue, 10 Nov 2026 09:00:00 GMT", ""),
              ("Birla Corporation Limited", "https://bis/4", "", "Tue, 10 Nov 2026 10:00:00 GMT", ""))


class TestEventsAndReports(unittest.TestCase):
    TODAY = datetime(2026, 11, 13).date()

    def fetch(self, url):
        if url in EVENT_PAGES:
            return EVENT_PAGES[url].encode("utf-8")
        if url == "bisfeed":
            return REPORTS
        return fetcher(url)

    def test_rbi_drafts_with_deadlines(self):
        drafts = rw.read_rbi_drafts(self.fetch, self.TODAY)
        self.assertEqual([c.title[:20] for c in drafts], ["Priority Sector Lend", "Draft KYC Amendment "])  # old one dropped
        self.assertEqual(drafts[0].deadline, datetime(2026, 11, 26).date())
        self.assertEqual(drafts[0].days_left(self.TODAY), 13)
        self.assertEqual(rw._due(drafts[0], self.TODAY), "comments due 26 Nov (13 days)")

    def test_cafral_events(self):
        evs = rw.read_cafral_events(self.fetch)
        self.assertEqual([e.organiser for e in evs], ["CAFRAL", "CAFRAL"])            # /events/learning skipped
        self.assertEqual(evs[1].when, "3–4 Dec 2026")
        self.assertEqual(rw._place(evs[0].place), "Mumbai")
        self.assertEqual(rw._place("Online CISCO WebEx"), "Online")

    def test_gather_window_dedupe_and_open_only(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "events.json"
            f.write_text(json.dumps({"events": [
                {"name": "ECL Framework: Board Oversight Programme", "start": "2026-11-25"},   # also from CAFRAL
                {"name": "Too far away", "start": "2027-06-01"},
                {"name": "Already over", "start": "2026-11-01", "end": "2026-11-02"},
                {"name": "Fraud summit", "start": "2026-11-20", "url": "https://x"},
                {"name": "No date"}]}), encoding="utf-8")
            evs, cons, errs = rw.gather_events({"file": str(f), "window_days": 60}, self.fetch, self.TODAY)
        self.assertEqual([e.name for e in evs], ["Fraud summit", "ECL Framework: Board Oversight Programme",
                                                 "Programme on KYC/AML for Senior Executives"])
        self.assertEqual([c.title[:8] for c in cons], ["Priority"])        # the KYC draft closed on 31 Oct
        self.assertEqual(errs, [])
        def broken(url):
            raise OSError("down")
        evs, cons, errs = rw.gather_events({"file": str(pathlib.Path(d) / "none.json")}, broken, self.TODAY)
        self.assertEqual((evs, cons), ([], []))
        self.assertEqual(len(errs), 2)                                    # reported, not fatal

    def test_reports_kept_out_of_blocks_and_shown_everywhere(self):
        src = dict(SOURCES, reports={"feeds": [{"name": "BIS publications", "url": "bisfeed", "weight": 0.6}]},
                   events={"file": "/no/such/events.json", "window_days": 60})
        res = rw.run(top=3, sources=src, fetcher=self.fetch, now=NOW + rw.timedelta(days=8))
        self.assertNotIn("https://bis/1", [s.lead.link for s in res.top])
        self.assertIn("https://bis/1", [s.lead.link for s in res.reports])
        self.assertNotIn("https://bis/4", [s.lead.link for s in res.reports])      # a company rating, no risk
        self.assertIn("Consultation paper on anti-money laundering norms", [s.lead.title for s in res.reports])
        self.assertEqual([c.title[:8] for c in res.consultations], ["Priority"])
        self.assertEqual(len(res.events), 2)
        md = rw.to_markdown(res)
        self.assertIn("## Events & reports", md)
        self.assertIn("comments due 26 Nov (13 days)", md)
        page = rw.to_html(res)
        self.assertIn("Events &amp; reports", page)
        self.assertIn("<h3>Upcoming</h3>", page)
        self.assertIn("EVENTS & REPORTS", rw.to_console(res, {}))
        week = rw.to_confluence(res)
        import xml.etree.ElementTree as ET
        ET.fromstring('<r xmlns:ac="a" xmlns:ri="b">' + week + "</r>")
        self.assertLess(week.index("Events &amp; reports"), len(week))
        res.events_max = 1                                    # show the nearest; the rest one click away
        self.assertIn("[All 2 events in the next 60 days](risk-week-2026-11-13-events.html)", rw.to_markdown(res))
        self.assertIn('href="risk-week-2026-11-13-events.html"', rw.to_html(res))
        self.assertEqual(rw.to_html(res).count("Programme on KYC/AML"), 0)
        self.assertIn('ac:parameter ac:name="title">All 2 events', rw.to_confluence(res))
        conf = rw.to_confluence(res)
        self.assertIn("<th>Comments &amp; deadlines</th><th>Upcoming</th><th>New reports</th>", conf)   # grouped in blocks
        self.assertIn("13 days left", conf)
        ET.fromstring('<r xmlns:ac="a" xmlns:ri="b">' + conf + "</r>")
        with tempfile.TemporaryDirectory() as d:
            files = rw.write(res, d)
            allpage = pathlib.Path(files["events"]).read_text(encoding="utf-8")
        self.assertIn("Programme on KYC/AML", allpage)
        res.events_max = 10
        try:
            from pptx import Presentation
        except ImportError:
            return
        with tempfile.TemporaryDirectory() as d:
            files = rw.write(res, d)
            titles = [[sh.text_frame.text for sh in sl.shapes if sh.has_text_frame][0]
                      for sl in Presentation(files["pptx"]).slides]
        self.assertIn("Events & reports", "\n".join(titles))

    def test_shipped_events_file_reads(self):
        self.assertTrue(rw.load_events_file(pathlib.Path(rw.__file__).with_name("events.json")))


PF_NEWS = {
    "Acme Steel": rss(
        ("Acme Steel defaults on bond interest, lenders move NCLT", "https://pf/1", "", "Wed, 04 Nov 2026 08:00:00 GMT", "ET"),
        ("Acme Steel misses interest payment; NCLT plea by lenders", "https://pf/2", "", "Wed, 04 Nov 2026 09:00:00 GMT", "BS"),
        ("Steel prices fall in October", "https://pf/3", "Acme Steel among producers", "Wed, 04 Nov 2026 10:00:00 GMT", "ET"),
        ("Acme Steel wins award in 2025", "https://pf/4", "", "Mon, 05 Oct 2026 10:00:00 GMT", "ET"),
        ("Stocks to watch today: Acme Steel, Infosys", "https://pf/6", "", "Wed, 04 Nov 2026 07:00:00 GMT", "ET")),
    "Bharat Power": rss(
        ("Bharat Power bags ₹2,000 crore order from NTPC", "https://pf/5", "", "Tue, 03 Nov 2026 10:00:00 GMT", "Mint"),
        ("bpl tie-up announced", "https://pf/7", "", "Tue, 03 Nov 2026 11:00:00 GMT", "Mint")),   # short alias: case
    "Quiet Co": rss(),
}


def pf_fetcher(url):
    import urllib.parse
    if url.startswith("https://news.google.com/"):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["q"][0]
        for name, body in PF_NEWS.items():
            if f'"{name}"' in q:
                return body
    return fetcher(url)


class TestPortfolio(unittest.TestCase):
    def write_file(self, d, text="# my borrowers\n1. Acme Steel Limited\nBharat Power Ltd | BPL\nQuiet Co\nacme steel limited\n"):
        f = pathlib.Path(d) / "top 20.txt"
        f.write_text(text, encoding="utf-8")
        return f

    def sources(self, f):
        return dict(SOURCES, portfolio={"file": str(f)})

    def test_load_file(self):
        with tempfile.TemporaryDirectory() as d:
            cs = rw.load_portfolio(self.write_file(d))
            self.assertEqual([c.name for c in cs], ["Acme Steel Limited", "Bharat Power Ltd", "Quiet Co"])
            self.assertEqual(cs[1].aliases, ["BPL"])
            self.assertEqual(cs[0].query, '"Acme Steel"')
            self.assertEqual(cs[1].query, '"Bharat Power" OR "BPL"')
            f = pathlib.Path(d) / "cp.txt"
            f.write_bytes("Société Générale\n".encode("cp1252"))        # Notepad in the Windows code page
            self.assertEqual(rw.load_portfolio(f)[0].name, "Société Générale")

    def test_flags(self):
        self.assertEqual(rw.ews_flags("Lenders drag X to NCLT")[0], ("Default / insolvency", "red"))
        self.assertEqual(rw.ews_flags("CRISIL downgrades X to BB")[0][1], "red")
        self.assertEqual(rw.ews_flags("ED raids X promoters")[0][0], "Fraud / enforcement")
        self.assertEqual(rw.ews_flags("X auditor resigns")[0][1], "amber")
        self.assertEqual(rw.ews_flags("X bags order worth ₹500 crore")[0][1], "green")
        self.assertEqual(rw.ews_flags("X to hold AGM on Friday"), [])

    def test_scan_render_and_never_to_gemini(self):
        sent = []

        class Spy:
            name, model = "spy", "spy-1"

            def json_call(self, system_prompt, user_content, response_schema=None, max_output_tokens=0):
                sent.append(system_prompt + user_content)
                return {"items": [{"id": 1, "category": "Credit risk", "impact": 6, "headline": "H",
                                   "why_it_matters": "W"}], "radar": [], "cro_focus": {"id": 1, "message": "m"}}

        with tempfile.TemporaryDirectory() as d:
            res = rw.run(top=3, sources=self.sources(self.write_file(d)), fetcher=pf_fetcher, now=NOW, provider=Spy())
            for text in sent:
                for secret in ("Acme", "Bharat Power", "BPL", "Quiet Co", "https://pf/"):
                    self.assertNotIn(secret, text)                # borrowers never reach Gemini
            acme, bharat, quiet = res.portfolio
            self.assertEqual(len(acme.stories), 1)                # two outlets, one story; no-name and old dropped
            self.assertEqual(len(acme.stories[0].items), 2)
            self.assertEqual(acme.signal, ("Default / insolvency", "red"))
            self.assertEqual(bharat.signal[1], "green")
            self.assertEqual(len(bharat.stories), 1)               # "bpl" is not "BPL"
            self.assertEqual(quiet.stories, [])
            self.assertEqual([c.name for c in rw.portfolio_order(res.portfolio)], ["Acme Steel Limited", "Bharat Power Ltd"])
            self.assertEqual(rw._pf_counts(res.portfolio),
                             "3 names · 2 with news · 1 red · 1 positive · 1 share-price or non-credit headline left out")
            self.assertNotIn("https://pf/1", [s.lead.link for s in res.top])   # not in the six blocks
            md = rw.to_markdown(res)
            self.assertIn("## Credit portfolio watch", md)
            self.assertIn("**Red · Default / insolvency**", md)
            self.assertIn("No credit news this week: Quiet Co", md)
            page = rw.to_html(res)
            self.assertIn('<li class="red">', page)
            self.assertIn("CREDIT PORTFOLIO WATCH", rw.to_console(res, {}))
            body = rw.to_confluence(res)
            import xml.etree.ElementTree as ET
            ET.fromstring('<r xmlns:ac="a" xmlns:ri="b">' + body + "</r>")
            self.assertIn("Credit portfolio watch", body)
            try:
                from pptx import Presentation
            except ImportError:
                return
            files = rw.write(res, d)
            text = "\n".join(sh.text_frame.text for sl in Presentation(files["pptx"]).slides
                             for sh in sl.shapes if sh.has_text_frame)
            self.assertIn("Credit portfolio watch", text)

    def test_search_failure_and_missing_file_not_fatal(self):
        def broken(url):
            if "Acme" in urllib.parse.unquote_plus(url):
                raise OSError("down")
            return pf_fetcher(url)
        import urllib.parse
        with tempfile.TemporaryDirectory() as d:
            res = rw.run(top=3, sources=self.sources(self.write_file(d)), fetcher=broken, now=NOW)
            self.assertTrue(any("Portfolio search (Acme Steel Limited)" in e for e in res.errors))
            self.assertEqual(res.portfolio[1].signal[1], "green")
            res = rw.run(top=3, sources=self.sources(pathlib.Path(d) / "none.txt"), fetcher=pf_fetcher, now=NOW)
            self.assertEqual(res.portfolio, [])
            self.assertNotIn("Credit portfolio watch", rw.to_html(res))

    def test_gigacode_notes(self):
        with tempfile.TemporaryDirectory() as d:
            f = self.write_file(d)
            srv = rw.McpServer(fetcher=pf_fetcher, sources=self.sources(f), now=NOW,
                               out_dir=pathlib.Path(d) / "out", base_dir=pathlib.Path(d))
            r = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                            "params": {"name": "risk_week_prepare", "arguments": {}}})
            text = r["result"]["content"][0]["text"]
            self.assertIn("## Credit portfolio watch", text)
            self.assertIn("Acme Steel misses interest payment", text)   # newest headline leads the story
            self.assertNotIn("- Quiet Co", text)                 # only companies with news
            batch = text.split("Batch: ")[1].split("\n")[0]
            lines = {int(l[1:l.index("]")]): l for l in text.split("Candidates:\n")[1].splitlines() if l.startswith("[")}
            ecl = next(k for k, v in lines.items() if "expected credit loss" in v)
            ranking = {"items": [{"id": ecl, "category": "Credit risk", "impact": 9, "headline": "ECL draft",
                                  "why_it_matters": "W"}], "radar": [], "cro_focus": {"id": ecl, "message": "m"},
                       "portfolio": [{"company": "Bharat Power Ltd", "signal": "none", "note": "Routine order news."},
                                     {"company": "Acme Steel", "signal": "red", "note": "Call the RM today."}]}
            r = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "risk_week_publish", "arguments": {"batch": batch, "ranking": ranking, "publish": False}}})
            reply = r["result"]["content"][0]["text"]
            self.assertFalse(r["result"]["isError"], reply)
            self.assertIn("Credit portfolio watch: 3 names", reply)
            md = next((pathlib.Path(d) / "out").glob("*.md")).read_text(encoding="utf-8")
            self.assertIn("GigaCode: Call the RM today.", md)
            self.assertIn("| Bharat Power Ltd | News |", md)      # GigaCode overrode the keyword flag


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
        self.assertEqual(len(sent), 3)                             # rank, fill_why, deep dive
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
        self.assertEqual(len(ai.prompts), 3)                      # rank, fill_why, deep dive
        kept = next(s for s in res.top if s.why == "Has one.")
        self.assertNotIn(kept.lead.title, ai.prompts[1])          # only the missing ones are asked again
        self.assertEqual([e["request"] for e in res.ai_log], ["rank", "fill_why", "deep_dive"])

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

        res = rw.run(top=3, sources={**SOURCES, "deep_dive": False}, fetcher=fetcher, now=NOW,
                     provider=rw.GeminiProvider(post=post, sleep=waits.append))   # deep dive off: count the ranking retries only
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


class TestDeepDive(unittest.TestCase):
    """The CRO deep dive (docs/spec-cro-deep-dive.md): fetch the story of the week's articles,
    then one analysis call; in md, html, pptx, console and Confluence; never fatal."""

    DD = {"what_happened": "RBI published the draft ECL directions on 3 Nov 2026. They apply from 1 April 2027.",
          "why_it_matters": "Models, provisioning and capital planning must change together.",
          "impact_on_us": "MSME staging shifts and provisions rise from April 2027.",
          "regulatory_context": "Draft directions under section 35A of the Banking Regulation Act.",
          "recommended_actions": ["Credit team to size the MSME ECL impact by 28 Nov",
                                  "Model risk to list affected models by 5 Dec"],
          "watch_next": "The consultation deadline and the final direction."}

    @staticmethod
    def art_fetcher(url):
        """Feeds as usual; every other link answers with a readable article page."""
        try:
            return fetcher(url)
        except OSError:
            return f"<html><nav>ads</nav><p>{'article detail ' * 100}</p></html>".encode()

    def ai(self):
        return SeqAI({"items": [{"id": 1, "category": "Credit risk", "impact": 7, "headline": "Deep dive story",
                                 "why_it_matters": "W"}], "radar": [], "cro_focus": {"id": 1, "message": "m"}},
                     self.DD)

    def test_extract_article(self):
        page = (b"<head><style>a{color}</style><script>evil()</script></head><body>"
                b"<nav>menu</nav><h1>Headline</h1><p>First   para.</p>"
                b"<ul><li>Point   one</li></ul><footer>ads</footer></body>")
        text = rw.extract_article(page)
        self.assertEqual(text, "Headline\nFirst para.\nPoint one")
        self.assertEqual(rw.extract_article(b"<p>" + b"x" * 50 + b"</p>", cap=10), "x" * 10)

    def test_fetch_story_text_lead_first_unique_and_capped(self):
        items = [rw.Item(title=f"T{n}", link=l, source="s", published=NOW)
                 for n, l in enumerate(["a", "b", "c", "c", "d", "e", "f"])]
        story = rw.Story(items=items, category="Credit risk", score=1)
        good = f"<p>{'word ' * 300}</p>".encode()

        def art(url):
            if url in ("a", "c", "e", "f"):
                return good
            if url == "b":
                return b"<p>too short</p>"                    # a stub or a paywall page
            raise OSError("403")

        out = rw.fetch_story_text(story, fetcher=art)
        self.assertEqual([it.link for it, _ in out], ["a", "c", "e"])     # lead first, max 3, bad links skipped

    def test_parse_validates_and_caps(self):
        d = rw.parse_deep_dive(dict(self.DD, recommended_actions=[f"a{n}" for n in range(6)]))
        self.assertEqual(d["recommended_actions"], ["a0", "a1", "a2", "a3"])      # at most 4
        self.assertIsNone(rw.parse_deep_dive({"what_happened": "x"}))             # impact_on_us missing
        self.assertIsNone(rw.parse_deep_dive("not json"))
        self.assertIsNone(rw.parse_deep_dive(None))
        d = rw.parse_deep_dive(dict(self.DD, what_happened="w " * 2000,
                                    recommended_actions="call the RM; review models"))  # a string, not a list
        self.assertEqual(d["recommended_actions"], ["call the RM", "review models"])
        self.assertLessEqual(len(d["what_happened"]), rw.DEEP_DIVE_CHARS)

    def test_run_builds_deep_dive_into_every_output(self):
        ai = self.ai()
        res = rw.run(top=3, sources=SOURCES, fetcher=self.art_fetcher, now=NOW, provider=ai)
        self.assertIsNotNone(res.deep_dive)
        self.assertIs(res.deep_dive.story, res.cro_focus.story)
        self.assertEqual(len(ai.prompts), 2)                        # rank, deep dive (no fill_why needed)
        self.assertIn("Full article text", ai.prompts[1])           # the articles were fetched for it
        self.assertIn("recommended_actions", ai.prompts[1])
        self.assertEqual([a["link"] for a in res.deep_dive.articles][0], res.cro_focus.story.lead.link)
        self.assertEqual(res.deep_dive.note, "")
        self.assertEqual([e["request"] for e in res.ai_log], ["rank", "deep_dive"])
        md = rw.to_markdown(res)
        self.assertIn("## CRO DEEP DIVE", md)
        self.assertIn("- [ ] Credit team to size the MSME ECL impact by 28 Nov", md)
        self.assertIn("Sources consulted", md)
        page = rw.to_html(res)
        self.assertIn("CRO deep dive", page)
        self.assertLess(page.index('<div class="blocks">'), page.index('class="panel deepdive"'))
        self.assertIn("<ol>", page[page.index("panel deepdive"):])  # the actions as an ordered list
        conf = rw.to_confluence(res)
        import xml.etree.ElementTree as ET
        ET.fromstring('<r xmlns:ac="a" xmlns:ri="b">' + conf + "</r>")
        self.assertLess(conf.index("rtw-week-"), conf.index("CRO deep dive"))     # inside the run's entry
        self.assertIn("Deep dive: 2 recommended actions", rw.to_console(res, {}))
        try:
            from pptx import Presentation
        except ImportError:
            return
        with tempfile.TemporaryDirectory() as d:
            files = rw.write(res, d)
            slides = Presentation(files["pptx"]).slides
            slide1 = "\n".join(sh.text_frame.text for sh in slides[0].shapes if sh.has_text_frame)
            self.assertTrue(slide1.startswith(rw._title(res)))      # slide 1 stays 'For CRO's desk'
            self.assertIn(rw.CRO_TITLE, slide1)
            dd_texts = [sh.text_frame.text for sh in slides[1].shapes if sh.has_text_frame]
        self.assertIn("CRO deep dive", dd_texts[0])                 # its own slide, right after slide 1
        self.assertIn("Credit team to size", "\n".join(dd_texts))

    def test_articles_unreachable_still_analysed_with_note(self):
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=self.ai())
        self.assertIsNotNone(res.deep_dive)                          # the plain fetcher reads no article
        self.assertIn("not reachable", res.deep_dive.note)
        self.assertIn("headlines and summaries", rw.to_html(res))

    def test_deep_dive_failure_leaves_the_report_intact(self):
        class Boom:
            name, model = "boom", "b1"

            def json_call(s, system, user, response_schema=None, max_output_tokens=0):
                if "CRO deep dive" in user:
                    raise RuntimeError("HTTP 503 busy")
                return {"items": [{"id": 1, "category": "Credit risk", "impact": 7, "headline": "H",
                                   "why_it_matters": "W"}], "radar": [], "cro_focus": {"id": 1, "message": "m"}}

        res = rw.run(top=3, sources=SOURCES, fetcher=self.art_fetcher, now=NOW, provider=Boom())
        self.assertTrue(res.top and res.cro_focus)                   # the report itself stands
        self.assertIsNone(res.deep_dive)
        self.assertIn("unavailable", res.deep_dive_note)
        self.assertIn("Deep dive: unavailable", rw.to_console(res, {}))
        self.assertNotIn("CRO deep dive", rw.to_html(res))
        entry = next(e for e in res.ai_log if e.get("request") == "deep_dive")
        self.assertIn("HTTP 503", entry["error"])

    def test_switched_off_by_flag_or_sources(self):
        ai = self.ai()
        res = rw.run(top=3, sources=SOURCES, fetcher=self.art_fetcher, now=NOW, provider=ai, deep_dive=False)
        self.assertIsNone(res.deep_dive)
        self.assertEqual(len(ai.prompts), 1)                         # no deep-dive call at all
        ai2 = self.ai()
        res = rw.run(top=3, sources={**SOURCES, "deep_dive": False}, fetcher=self.art_fetcher, now=NOW, provider=ai2)
        self.assertIsNone(res.deep_dive)
        self.assertEqual(len(ai2.prompts), 1)

    def test_keywords_run_skips_with_a_note(self):
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW)
        self.assertIsNone(res.deep_dive)
        self.assertIn("Deep dive: skipped (AI off)", rw.to_console(res, {}))
        self.assertNotIn("panel deepdive", rw.to_html(res))

    def test_finish_week_attaches_it_only_while_the_story_survives(self):
        week = rw.prepare_week(sources=TestSafetyNet.SRC, fetcher=lambda u: TestSafetyNet.NEWS, now=NOW)
        mudra = next(s for s in week.stories if "Mudra" in s.lead.title)
        coop = next(s for s in week.stories if "Abhyudaya" in s.lead.title)
        dd = rw.parse_deep_dive(self.DD)
        pick = rw.AiPick(blocks={b: ([mudra] if b == "Credit risk" else []) for b in rw.BLOCKS},
                         focus=rw.CroFocus(mudra, "m"), deep_dive=dd)
        res = rw.finish_week(week, 3, pick, "AI · GigaCode via MCP")
        self.assertIs(res.deep_dive.story, mudra)                    # the story held: the dive stays
        self.assertEqual([a["link"] for a in res.deep_dive.articles], ["https://g/mudra"])
        pick = rw.AiPick(blocks={b: ([coop] if b == "Compliance risk" else []) for b in rw.BLOCKS},
                         focus=rw.CroFocus(coop, "m"), deep_dive=dd)
        res = rw.finish_week(week, 3, pick, "AI · GigaCode via MCP")
        self.assertIsNone(res.deep_dive)                             # safety net replaced the story
        self.assertIn({"deep_dive": "dropped: the story of the week changed"}, res.ai_log)


class TestDeepDiveMcp(unittest.TestCase):
    """GigaCode fetches and writes the deep dive itself; the server validates and places it."""

    def call(self, srv, name, args=None):
        r = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": name, "arguments": args or {}}})
        return r["result"]["content"][0]["text"], r["result"]["isError"]

    def server(self, d):
        base = pathlib.Path(d)
        return rw.McpServer(fetcher=fetcher, sources=SOURCES, now=NOW, out_dir=base / "out", base_dir=base)

    def publish(self, d, deep_dive):
        srv = self.server(d)
        text, err = self.call(srv, "risk_week_prepare")
        self.assertFalse(err)
        self.assertIn("5. deep_dive", text)                          # step 5 is in the instructions
        self.assertIn('"deep_dive"', text)                           # and in the answer-format example
        batch = text.split("Batch: ")[1].split("\n")[0]
        lead = srv.pool[0].lead.title
        ranking = {"items": [{"id": 1, "category": "Credit risk", "impact": 7, "headline": lead,
                              "why_it_matters": "W"}], "radar": [], "cro_focus": {"id": 1, "message": "m"}}
        if deep_dive is not None:
            ranking["deep_dive"] = deep_dive
        reply, err = self.call(srv, "risk_week_publish", {"batch": batch, "ranking": ranking, "publish": False})
        self.assertFalse(err, reply)
        md = next((pathlib.Path(d) / "out").glob("*.md")).read_text(encoding="utf-8")
        return reply, md

    def test_gigacode_deep_dive_is_published(self):
        with tempfile.TemporaryDirectory() as d:
            reply, md = self.publish(d, TestDeepDive.DD)
            self.assertIn("CRO deep dive: written", reply)
            self.assertIn("## CRO DEEP DIVE", md)
            self.assertIn("Credit team to size the MSME ECL impact by 28 Nov", md)

    def test_missing_or_malformed_deep_dive_is_ignored(self):
        for junk in (None, "just words", {"what_happened": "only half"}):
            with tempfile.TemporaryDirectory() as d:
                reply, md = self.publish(d, junk)
                self.assertNotIn("## CRO DEEP DIVE", md)             # the report publishes as before
                self.assertNotIn("CRO deep dive: written", reply)


def ids_by_title(user):
    """{title prefix: id} from a ranking prompt's candidate lines."""
    lines = user.split("Candidates:\n")[1].splitlines()
    return {l.split(") ", 1)[1]: int(l[1:l.index("]")]) for l in lines if l.startswith("[")}


class TitleAI:
    """Answers the ranking request with picks named by title prefix: (prefix, block, checks[, deadline])."""
    name, model = "fake", "f"

    def __init__(self, picks, focus=None):
        self.picks, self.focus, self.sent = picks, focus, []

    def json_call(self, system, user, response_schema=None, max_output_tokens=0):
        self.sent.append(system + user)
        if "Candidates:" not in user:
            return {"items": []}
        ids = ids_by_title(user)
        i = lambda pre: next(v for k, v in ids.items() if k.startswith(pre))  # noqa: E731
        items = []
        for pick in self.picks:
            pre, block, checks = pick[:3]
            r = {"id": i(pre), "category": block, "headline": pre, "why_it_matters": "w", "checks": checks}
            if len(pick) > 3:
                r["deadline"] = pick[3]
            items.append(r)
        return {"items": items, "radar": [],
                "cro_focus": {"id": i(self.focus or self.picks[0][0]), "message": "m"}}


CHK = lambda india, business, action, size: {"india": india, "business": business,  # noqa: E731
                                             "action": action, "size": size}


class TestChecklist(unittest.TestCase):
    def test_impact_is_the_total_and_india_zero_is_capped(self):
        self.assertEqual(rw.impact_of(CHK(3, 2, 2, 1)), 8)
        self.assertEqual(rw.impact_of(CHK(0, 3, 2, 2)), 4)          # the India test, built in
        self.assertEqual(rw.impact_of(CHK(0, 0, 0, 0)), 1)
        self.assertEqual(rw.score_checks({"india": 9, "business": -1, "action": "2", "size": 1}),
                         CHK(3, 0, 2, 1))                           # clamped to each range
        self.assertIsNone(rw.score_checks({"india": 3, "business": 2}))   # a missing check
        self.assertEqual(rw.AI_SCHEMA["properties"]["items"]["items"]["required"],
                         ["id", "headline", "category", "checks", "why_it_matters"])

    def test_ranking_uses_the_checklist_and_shows_it(self):
        ai = TitleAI([("RBI issues draft", "Compliance risk", CHK(3, 2, 2, 2)),
                      ("Major private bank", "Cyber security risk", CHK(2, 1, 1, 1)),
                      ("Bank NPA", "Credit risk", CHK(0, 2, 1, 2))])      # india 0 -> 4 -> dropped
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=ai, deep_dive=False)
        self.assertIn("india 0-3", ai.sent[0])
        ecl = res.blocks["Compliance risk"][0]
        self.assertEqual((ecl.impact, ecl.checks), (9, CHK(3, 2, 2, 2)))
        self.assertEqual(res.blocks["Cyber security risk"][0].impact, 5)
        self.assertEqual(res.blocks["Credit risk"], [])                   # capped at 4, then dropped
        d = ecl.as_dict()
        self.assertEqual(rw.impact_label(d), "Impact 9/10 (India 3 · Business 2 · Action 2 · Size 2)")
        self.assertIn("Impact 9/10 (India 3 · Business 2 · Action 2 · Size 2)", rw.to_markdown(res))
        self.assertIn('<span class="checks">(India 3 · Business 2 · Action 2 · Size 2)</span>', rw.to_html(res))
        self.assertIn("Impact 9/10 (India 3", rw.to_console(res, {}))
        self.assertIn("Impact 9/10 (India 3", rw.to_confluence(res))

    def test_old_single_rating_still_works(self):
        ai = FakeAI({"items": [{"id": 1, "category": "Credit risk", "impact": 7, "headline": "H",
                                "why_it_matters": "w"}], "radar": [], "cro_focus": {"id": 1, "message": "m"}})
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=ai, deep_dive=False)
        st = res.blocks["Credit risk"][0]
        self.assertEqual((st.impact, st.checks), (7, None))
        self.assertEqual(rw.impact_label(st.as_dict()), "Impact 7/10")


class TestNewsDeadlines(unittest.TestCase):
    def story(self, title, summary=""):
        return rw.Story([rw.Item(title, "https://x/1", "RBI", NOW, summary)], "Compliance risk", 1.0)

    def test_dates_written_in_text(self):
        full, months, days = rw.stated_dates("comments by December 15, 2026; effective 1st April 2027; "
                                             "by 31.03.2027; phased in from March 2028; on 20 Dec")
        from datetime import date
        self.assertTrue({date(2026, 12, 15), date(2027, 4, 1), date(2027, 3, 31)} <= full)
        self.assertIn((2028, 3), months)
        self.assertIn((12, 20), days)

    def test_only_a_stated_date_is_kept(self):
        from datetime import date
        s = self.story("RBI draft on ECL", "Comments by December 15, 2026. Effective from March 2027.")
        dl = rw.news_deadline({"date": "2026-12-15", "kind": "comments due"}, s)
        self.assertEqual((dl.when, dl.kind, dl.text()), (date(2026, 12, 15), "comments due", "Comments due 15 Dec 2026"))
        self.assertIsNone(rw.news_deadline({"date": "2026-12-16", "kind": "comments due"}, s))   # not in the text
        self.assertEqual(rw.news_deadline({"date": "2027-03-01", "kind": "takes effect"}, s).when,
                         date(2027, 3, 31))                        # 'March 2027' -> end of March
        self.assertEqual(rw.news_deadline({"date": "2026-12-15", "kind": "soon"}, s).kind, "deadline")
        self.assertIsNone(rw.news_deadline({"date": "15 Dec 2026", "kind": "comments due"}, s))  # not ISO
        old = self.story("Old rule", "issued on 10 January 2020")
        self.assertIsNone(rw.news_deadline({"date": "2020-01-10", "kind": "takes effect"}, old))  # too far back

    def test_deadlines_reach_the_item_and_events(self):
        ai = TitleAI([("RBI issues draft", "Compliance risk", CHK(3, 2, 2, 2),
                       {"date": "2027-04-01", "kind": "takes effect"}),          # stated: 'April 1, 2027'
                      ("Major private bank", "Cyber security risk", CHK(2, 1, 1, 1),
                       {"date": "2026-12-01", "kind": "compliance deadline"})])   # invented: dropped
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=ai, deep_dive=False)
        ecl, cyber = res.blocks["Compliance risk"][0], res.blocks["Cyber security risk"][0]
        self.assertEqual(ecl.as_dict()["deadline"], "Takes effect 1 Apr 2027")
        self.assertIsNone(cyber.deadline)
        self.assertEqual([(c.kind, c.url) for c in res.consultations], [("takes effect", "https://rbi/2")])
        md = rw.to_markdown(res)
        self.assertIn("**Takes effect 1 Apr 2027**", md)
        self.assertIn("**Comments & deadlines**", md)
        self.assertIn("takes effect 1 Apr (", md)
        self.assertIn('<p class="tag">Takes effect 1 Apr 2027</p>', rw.to_html(res))

    def test_listed_draft_is_not_repeated(self):
        from datetime import date
        st = self.story("RBI draft directions on priority sector lending", "Comments by December 15, 2026.")
        st.deadline = rw.NewsDeadline(date(2026, 12, 15), "comments due")
        rbi = rw.Consultation("Priority Sector Lending – Draft Directions", "https://rbi/psl",
                              deadline=date(2026, 12, 15))
        self.assertEqual(rw.add_news_deadlines([rbi], [st], NOW.date()), [rbi])


class TestBorrowerLink(unittest.TestCase):
    PORTFOLIO = ("Major Private Bank Ltd | Major private bank\n"
                 "Example Finance Ltd | sector: microfinance, gold loan\n")

    def sources(self, d):
        f = pathlib.Path(d) / "top 20.txt"
        f.write_text(self.PORTFOLIO, encoding="utf-8")
        return dict(SOURCES, portfolio={"file": str(f), "search": False})

    def test_sectors_read_from_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "top 20.txt"
            f.write_text("Acme Steel Ltd | Acme | Sector: steel; power\nPlain Co\n", encoding="utf-8")
            acme, plain = rw.load_portfolio(f)
            self.assertEqual((acme.aliases, acme.sectors), (["Acme"], ["steel", "power"]))
            self.assertEqual((plain.aliases, plain.sectors), ([], []))

    def test_ai_impact_raised_and_tagged_on_this_computer(self):
        ai = TitleAI([("Major private bank", "Cyber security risk", CHK(1, 1, 0, 1)),     # 3: kept only as our borrower
                      ("Bank NPA", "Credit risk", CHK(2, 1, 1, 1)),               # 5 + 1 (our sector)
                      ("RBI issues draft", "Compliance risk", CHK(3, 2, 2, 2))],
                     focus="RBI issues draft")
        with tempfile.TemporaryDirectory() as d:
            res = rw.run(top=3, sources=self.sources(d), fetcher=fetcher, now=NOW, provider=ai, deep_dive=False)
        for text in ai.sent:                                             # names and sectors stay here
            for secret in ("Major Private Bank Ltd", "Example Finance", "gold loan"):
                self.assertNotIn(secret, text)
        cyber, npa = res.blocks["Cyber security risk"][0], res.blocks["Credit risk"][0]
        self.assertEqual((cyber.impact, cyber.boost), (5, ["+2 our borrower"]))
        self.assertEqual(cyber.as_dict()["exposure"], "Our borrower: Major Private Bank")
        self.assertEqual((npa.impact, npa.boost, npa.sectors), (6, ["+1 our sector"], ["microfinance"]))
        self.assertEqual(rw.impact_label(npa.as_dict()),
                         "Impact 6/10 (India 2 · Business 1 · Action 1 · Size 1 · +1 our sector)")
        self.assertIn("**Our borrower: Major Private Bank**", rw.to_markdown(res))

    def test_keyword_ranking_raised(self):
        with tempfile.TemporaryDirectory() as d:
            plain = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW)
            linked = rw.run(top=3, sources=self.sources(d), fetcher=fetcher, now=NOW)
        score = lambda res, pre: next(s.score for s in res.top if s.lead.title.startswith(pre))  # noqa: E731
        self.assertAlmostEqual(score(linked, "Major private bank") - score(plain, "Major private bank"), rw.BORROWER_SCORE)
        self.assertAlmostEqual(score(linked, "Bank NPA") - score(plain, "Bank NPA"), rw.SECTOR_SCORE)

    def test_boost_once(self):
        st = rw.Story([rw.Item("Acme wins order", "l", "s", NOW)], "Credit risk", 1.0, impact=9)
        st.borrowers = ["Acme"]
        rw.boost_for_portfolio([st], ai=True)
        rw.boost_for_portfolio([st], ai=True)
        self.assertEqual(st.impact, 10)                                  # capped, and added once


class TestModelHealth(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}, clear=False)
        self.env.start()
        os.environ.pop("RISK_WEEK_MODEL", None)
        self.dir = tempfile.TemporaryDirectory()
        self.health = pathlib.Path(self.dir.name) / rw.HEALTH_FILE
        self.now = 1_800_000_000.0
        self.calls = []

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def provider(self, main_up=False):
        def post(url, body, headers):
            self.calls.append(url)
            if "3.8-flash" in url and not main_up:
                raise urllib.error.HTTPError(url, 503, "busy", {}, io.BytesIO(b"high demand"))
            return gemini_reply({"ok": True})
        return rw.GeminiProvider(post=post, sleep=lambda s: None, health=self.health, clock=lambda: self.now)

    def one_run(self, main_up=False):
        p = self.provider(main_up)
        p.json_call("s", "u")
        p.json_call("s", "u")                 # a run makes several calls: one failure counted
        return p

    def test_main_model_skipped_after_three_failed_runs_then_retried(self):
        for _ in range(3):
            self.one_run()
        self.assertEqual(json.loads(self.health.read_text())["gemini-3.8-flash"]["fails"], 3)
        self.calls.clear()
        p = self.one_run()
        self.assertFalse(any("3.8-flash" in u for u in self.calls))       # no 40 s of retries
        self.assertIn("skipped: failed 3 runs in a row", p.label)
        self.now += 25 * 3600                                             # a day later: try it again
        self.calls.clear()
        p = self.one_run(main_up=True)
        self.assertTrue(any("3.8-flash" in u for u in self.calls))
        self.assertEqual(p.label, "gemini-3.8-flash")
        self.assertEqual(json.loads(self.health.read_text())["gemini-3.8-flash"]["fails"], 0)

    def test_no_file_no_memory(self):
        p = rw.GeminiProvider(post=lambda u, b, h: gemini_reply({"ok": True}), sleep=lambda s: None)
        self.assertEqual(p.skip_reason("gemini-3.8-flash"), "")
        p.json_call("s", "u")

    def test_ai_check(self):
        report, ok = rw.ai_check(self.provider())
        self.assertTrue(ok)
        self.assertIn("gemini-3.8-flash: busy or unreachable (HTTP 503", report)
        self.assertIn("gemini-3.5-flash-lite: answered in", report)
        self.assertEqual(len(self.calls), 2)                              # one request each, no retries
        self.assertIn("Next --ai run starts with: gemini-3.8-flash", report)
        for _ in range(2):
            rw.ai_check(self.provider())
        report, _ = rw.ai_check(self.provider())
        self.assertIn("Next --ai run starts with: gemini-3.5-flash-lite (gemini-3.8-flash skipped", report)


class TestCreditDrivers(unittest.TestCase):
    """Real headlines from the 21 Nov 2026 company searches (Vedanta, Tata Steel, Adani Ports)."""
    KEPT = {
        "ONGC takes charge of Cambay block as Vedanta records ₹379 crore impairment": "Debt & liquidity",
        "India's Supreme Court Sends Vedanta's $358 Million Videocon Deal Back to Lenders": "Debt & liquidity",
        "Setback for Vedanta as Supreme Court upholds rejection of Twin Star's Videocon plan; stock falls nearly 3%":
            "Legal & regulatory",
        "Adani Ports ADANIPORTS Credit Rating Reaffirmed AAA": "Rating",
        "S&P says Adani Ports can absorb INR 27,000 crore Evos acquisition costs": "Rating",
        "Tata Steel shares slide nearly 2% as EU anti-dumping duty and bearish technicals weigh": "Legal & regulatory",
        "Vedanta Aluminium posts record Q2FY27 output, alumina up 37%": "Results",
        "Tata Steel and Utility Global Join Forces for Hydrogen Production at Kalinganagar": "Business & operations",
        "Tata Steel eyes 50 MT capacity, to direct 75% capex to India: TV Narendran": "Business & operations",
        "Adani Ports to acquire 100% stake in Evos in €2.56 billion deal": "Business & operations",
        "Chinese steel imports remain a threat to Indian industry, Tata Steel CEO says": "Business & operations",
        "Acme Infra CFO resigns with immediate effect": "Management & governance",
        "Finolex Cables maintains 12-12.5% margin outlook, expects competition from UltraTech to intensify": "Results",
        "Fitch Affirms UltraTech Cement's BBB- Ratings, Maintains Stable Outlook": "Rating",
        "UltraTech moves Supreme Court against BAI's role in CCI cement cartel probe": "Legal & regulatory",
    }
    DROPPED = [
        "Vedanta Share Price - Live NSE: VEDL Stock Price & Chart",
        "Vedanta shares fall over 3%, lead Nifty 100 losses as Citi cuts target price, flags zinc demand concerns",
        "Vedanta Aluminium, Hindustan Zinc: All 6 Vedanta Group stocks slide as global metal prices tumble; here is why",
        "Adani Ports & Special Economic Zone Ltd is Rated Hold",
        "Top stock picks: Analysts recommend Adani Ports, HDFC Bank, Reliance, M&M and 2 more stocks",
        "Billionaire Gautam Adani's group gets Jefferies buy calls",
        "Adani Ports and Special Economic Zone (NSEI:ADANIPORTS) Stock Forecast & Analyst Predictions",
        "Tata Steel Limited (TATASTEEL.NS) stock price, news, quote and history",
        "Vedanta Group Grants Additional 10% Salary to Nearly One Lakh Employees",
        "Vedanta Aluminium increases renewable energy use by 63% in FY26",
        "Adani: the billionaire at the heart of Modi’s India",
    ]

    def test_credit_news_kept_with_its_driver(self):
        for title, driver in self.KEPT.items():
            self.assertEqual(rw.credit_news(title), driver, title)

    def test_market_chatter_and_non_credit_news_dropped(self):
        for title in self.DROPPED:
            self.assertEqual(rw.credit_news(title), "", title)

    def test_share_price_fall_is_not_an_amber_flag(self):
        self.assertEqual(rw.ews_flags("Acme Steel shares fall 5% in weak market"), [])
        self.assertEqual(rw.ews_flags("Acme Steel posts Q2 loss")[0][1], "amber")

    def test_sector_word_must_sit_next_to_an_industry_term(self):
        self.assertTrue(rw.sector_hit("Are Chinese steel imports a threat to India?", "steel"))
        self.assertTrue(rw.sector_hit("India: NALCO cuts aluminium P1020 prices", "aluminium"))
        self.assertTrue(rw.sector_hit("Infrastructure spending driving robust cement demand", "cement"))
        self.assertFalse(rw.sector_hit("Mumbai man ports 26-year-old mediclaim policy", "ports"))
        self.assertFalse(rw.sector_hit("Adani Cement Deploys Heavy-Duty Electric Trucks", "cement"))

    def test_date_limit_first_when_the_query_has_brackets(self):
        import urllib.parse
        q = lambda url: urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["q"][0]  # noqa: E731
        self.assertTrue(q(rw.google_news_url('("Acme") (debt OR rating)', 7)).startswith("when:7d "))
        self.assertTrue(q(rw.google_news_url("bank risk", 7)).endswith(" when:7d"))

    def test_search_asks_for_credit_topics(self):
        c = rw.Company("Acme Steel Limited", ["ASL"])
        self.assertTrue(c.search_query.startswith('("Acme Steel" OR "ASL") ('))
        self.assertIn("lenders", c.search_query)


SW_NEWS = {
    "steel": rss(
        ("Steel prices fall as Chinese imports surge", "https://sw/1", "", "Wed, 04 Nov 2026 08:00:00 GMT", "ET"),
        ("Steel stocks to watch as Nifty Metal rises", "https://sw/2", "", "Wed, 04 Nov 2026 08:00:00 GMT", "ET"),
        ("Steel ministry plans safeguard duty on imports", "https://sw/3", "", "Tue, 03 Nov 2026 08:00:00 GMT", "BS")),
    "economy": rss(
        ("India's CPI inflation rises to 6.1% in October", "https://ec/1", "", "Wed, 04 Nov 2026 08:00:00 GMT", "Mint"),
        ("India inflation climbs to 6.1%, above RBI band", "https://ec/2", "", "Wed, 04 Nov 2026 09:00:00 GMT", "ET"),
        ("Sensex, Nifty fall as inflation worries weigh", "https://ec/3", "", "Wed, 04 Nov 2026 09:00:00 GMT", "ET"),
        ("US inflation cools in October", "https://ec/4", "", "Wed, 04 Nov 2026 09:00:00 GMT", "Reuters")),
}


def sw_fetcher(url):
    import urllib.parse
    if url.startswith("https://news.google.com/"):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["q"][0]
        if '"steel"' in q:
            return SW_NEWS["steel"]
        if "GDP" in q:
            return SW_NEWS["economy"]
    return pf_fetcher(url)


class TestSectorAndEconomy(unittest.TestCase):
    def run_it(self, d, provider=None):
        f = pathlib.Path(d) / "top 20.txt"
        f.write_text("Acme Steel Limited | sector: steel\nBharat Power Ltd | BPL\n", encoding="utf-8")
        return rw.run(top=3, sources=dict(SOURCES, portfolio={"file": str(f)}), fetcher=sw_fetcher, now=NOW,
                      provider=provider, deep_dive=False)

    def test_sector_and_economy_found_and_shown(self):
        with tempfile.TemporaryDirectory() as d:
            res = self.run_it(d)
            (steel,) = res.sector_watch
            self.assertEqual((steel.name, steel.companies), ("steel", ["Acme Steel"]))
            self.assertEqual({s.lead.link for s in steel.stories}, {"https://sw/1", "https://sw/3"})  # no stock tip
            self.assertEqual(len(res.economy), 1)                     # two outlets, one story; no Sensex, no US
            self.assertEqual(len(res.economy[0].items), 2)
            md = rw.to_markdown(res)
            self.assertIn("**Sector: steel** (Acme Steel)", md)
            self.assertIn("**Economy**", md)
            self.assertIn("Debt & liquidity · BS, 04 Nov", md)          # the driver on a borrower's story
            self.assertIn("Sector: steel", rw.to_html(res))
            self.assertIn("  Economy", rw.to_console(res, {}))
            body = rw.to_confluence(res)
            import xml.etree.ElementTree as ET
            ET.fromstring('<r xmlns:ac="a" xmlns:ri="b">' + body + "</r>")
            self.assertIn("<strong>Sector: steel</strong>", body)
            try:
                from pptx import Presentation
            except ImportError:
                return
            files = rw.write(res, d)
            titles = [sh.text_frame.text for sl in Presentation(files["pptx"]).slides for sh in sl.shapes
                      if sh.has_text_frame and sh.text_frame.text.startswith("Sector & economy watch")]
            self.assertEqual(len(titles), 1)

    def test_never_sent_to_the_ai(self):
        ai = TitleAI([("RBI issues draft", "Compliance risk", CHK(3, 2, 2, 2))])
        with tempfile.TemporaryDirectory() as d:
            self.run_it(d, provider=ai)
        for text in ai.sent:
            for secret in ("Steel prices fall as Chinese", "safeguard duty", "Acme Steel", "CPI inflation rises"):
                self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
