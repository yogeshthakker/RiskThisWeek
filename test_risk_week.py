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

    def test_no_ai_says_keywords(self):
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW)
        self.assertEqual(res.ai, "keywords (AI off)")
        self.assertTrue(all(s.impact is None for s in res.top))


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

        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=rw.GeminiProvider(post=post))
        self.assertIn("/models/gemini-3.8-flash:", urls[0])
        self.assertIn("/models/gemini-3.5-flash-lite:", urls[1])
        self.assertIn("gemini-3.5-flash-lite, after gemini-3.8-flash: free-tier limit", res.ai)
        self.assertIn("Lite", [s.headline for s in res.top])

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
