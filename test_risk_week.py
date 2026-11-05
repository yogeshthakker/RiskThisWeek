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
        self.prompt = ""

    def json_call(self, system_prompt, user_content, response_schema=None, max_output_tokens=1200):
        self.prompt = user_content
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
        self.res = rw.run(days=7, top=5, sources=SOURCES, fetcher=fetcher, now=NOW)
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

    def test_rbi_draft_ranks_first_and_lookback_ranked_low(self):
        self.assertIn("expected credit loss", self.titles[0])
        self.assertIn("DHFL", self.titles[-1])               # only there to fill the list

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
            self.assertIn("## 1. [RBI issues draft directions", md)        # headline is the link
            self.assertIn("](https://rbi/2)", md)
            self.assertIn("Routine enforcement, not ranked (3)", md)
            page = pathlib.Path(files["html"]).read_text(encoding="utf-8")
            self.assertIn('href="https://rbi/2" target="_blank"', page)
            self.assertIn("<details>", page)
            try:
                from pptx import Presentation
            except ImportError:
                self.assertNotIn("pptx", files)
                return
            slide = Presentation(files["pptx"]).slides[0]
            links = [(r.text, r.hyperlink.address) for sh in slide.shapes if sh.has_text_frame
                     for para in sh.text_frame.paragraphs for r in para.runs if r.hyperlink.address]
            self.assertIn(("Read ↗", "https://rbi/2"), links)
            self.assertTrue(any(text.startswith("RBI issues draft") for text, _ in links))

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
        self.assertEqual(res.top[0].headline, "Cyber attack hits UPI")
        self.assertEqual(len(res.top), 3)              # unknown id ignored, rest filled from ranking
        self.assertNotIn("invented", rw.to_markdown(res))
        self.assertTrue(res.ai.startswith("fake"))

    def test_unusable_reply_falls_back(self):
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=FakeAI({"answer": "x"}))
        self.assertIn("keyword ranking used", res.ai)
        self.assertEqual(len(res.top), 3)


class SeqAI:
    """Answers each request with the next reply in the list."""
    name, model = "seq", "seq-1"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def json_call(self, system_prompt, user_content, response_schema=None, max_output_tokens=1200):
        self.prompts.append(user_content)
        return self.replies.pop(0)


class TestSummariesAndCro(unittest.TestCase):
    def pick(self, items, focus=None):
        return {"items": items, "cro_focus": focus or {"id": 1, "message": "Ask Treasury to size it."}}

    def test_missing_why_filled_by_second_request(self):
        ai = SeqAI(
            self.pick([{"id": 1, "headline": "A", "category": "Capital", "why_it_matters": ""},
                       {"id": 2, "headline": "B", "category": "Capital", "why_it_matters": " "},
                       {"id": 3, "headline": "C", "category": "Capital", "why_it_matters": "Has one."}]),
            {"items": [{"id": 1, "why_it_matters": "Filled A."}, {"id": 2, "why_it_matters": "Filled B."}]},
        )
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=ai)
        self.assertEqual([s.why for s in res.top], ["Filled A.", "Filled B.", "Has one."])
        self.assertEqual(len(ai.prompts), 2)
        self.assertNotIn("Has one", ai.prompts[1])                # only the missing ones are asked again
        self.assertEqual([e["request"] for e in res.ai_log], ["pick", "fill_why"])

    def test_other_key_names_accepted(self):
        ai = SeqAI(self.pick([{"id": 1, "headline": "A", "category": "Capital", "why": "Via 'why'."}]))
        res = rw.run(top=1, sources=SOURCES, fetcher=fetcher, now=NOW, provider=ai)
        self.assertEqual(res.top[0].why, "Via 'why'.")
        self.assertEqual(len(ai.prompts), 1)

    def test_cro_focus_from_ai(self):
        ai = SeqAI(self.pick([{"id": 1, "headline": "A", "category": "Capital", "why_it_matters": "x"},
                              {"id": 2, "headline": "B", "category": "Capital", "why_it_matters": "y"}],
                             {"id": 2, "message": "Ask Credit to check exposure."}))
        res = rw.run(top=2, sources=SOURCES, fetcher=fetcher, now=NOW, provider=ai,
                     cro_notes=["RAS review to Board on 20 Nov"])
        box = rw.cro_box(res)
        self.assertEqual(box["notes"], ["RAS review to Board on 20 Nov"])
        self.assertEqual(box["focus"]["headline"], "B")
        self.assertEqual(box["focus"]["message"], "Ask Credit to check exposure.")
        self.assertIn("cro_focus", ai.prompts[0])

    def test_cro_focus_without_ai_is_top_item(self):
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW)
        self.assertIs(res.cro_focus.story, res.top[0])
        self.assertIsNotNone(rw.cro_box(res))

    def test_cro_box_in_every_format(self):
        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, cro_notes=["Board RAS review 20 Nov"],
                     provider=SeqAI(self.pick([{"id": 1, "headline": "A", "category": "Capital",
                                                "why_it_matters": "x"}])))
        with tempfile.TemporaryDirectory() as d:
            files = rw.write(res, d)
            md = pathlib.Path(files["markdown"]).read_text(encoding="utf-8")
            self.assertIn("> ### From the CRO's desk", md)
            self.assertIn("> - Board RAS review 20 Nov", md)
            self.assertIn("**Focus this week:**", md)
            page = pathlib.Path(files["html"]).read_text(encoding="utf-8")
            self.assertIn('<aside class="cro">', page)
            self.assertIn("Board RAS review 20 Nov", page)
            self.assertIn('"request": "pick"', pathlib.Path(files["ai_reply"]).read_text(encoding="utf-8"))
            self.assertIn("FROM THE CRO'S DESK", rw.to_console(res, files))
            try:
                from pptx import Presentation
            except ImportError:
                return
            texts = [sh.text_frame.text for sh in Presentation(files["pptx"]).slides[0].shapes
                     if sh.has_text_frame]
            panel = [x for x in texts if x.startswith("From the CRO's desk")]
            self.assertEqual(len(panel), 1)
            self.assertIn("Board RAS review 20 Nov", panel[0])
            self.assertIn("Focus this week", panel[0])

    def test_notes_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "cro_desk.txt"
            f.write_text("# comment\n\n- First note\nSecond note\n• Third\n", encoding="utf-8")
            self.assertEqual(rw.load_cro_notes(f), ["First note", "Second note", "Third"])
            self.assertEqual(rw.load_cro_notes(pathlib.Path(d) / "missing.txt"), [])

    def test_example_notes_file_parses(self):
        notes = rw.load_cro_notes(pathlib.Path(__file__).resolve().parent / "cro_desk.example.txt")
        self.assertEqual(len(notes), 2)


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
        self.assertEqual(g.model, "gemini-3.5-flash-lite")
        out = g.json_call("sys", "user", rw.AI_SCHEMA)
        self.assertEqual(out["items"][0]["headline"], "H")
        url, body, headers = calls[0]
        self.assertIn("/models/gemini-3.5-flash-lite:generateContent", url)
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
        self.assertTrue(res.ai.startswith("gemini (gemini-3.5-flash-lite)"))

    def test_daily_limit_falls_back_to_keywords(self):
        def post(url, body, headers):
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, io.BytesIO(b"quota"))

        res = rw.run(top=3, sources=SOURCES, fetcher=fetcher, now=NOW, provider=rw.GeminiProvider(post=post))
        self.assertIn("keyword ranking used", res.ai)
        self.assertEqual(len(res.top), 3)

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
