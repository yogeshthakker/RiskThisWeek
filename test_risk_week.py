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

    def test_routine_enforcement_rolled_up(self):
        roll = [s for s in self.res.top + self.res.radar if s.lead.title.startswith("RBI enforcement round-up")]
        self.assertEqual(len(roll), 1)
        self.assertIn("2 action", roll[0].lead.title)
        self.assertIn("Pusad", roll[0].lead.summary)

    def test_rbi_draft_ranks_first_and_lookback_ranked_low(self):
        self.assertIn("expected credit loss", self.titles[0])
        self.assertNotIn("DHFL", " ".join(self.titles))

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
            self.assertIn("<ol>", pathlib.Path(files["html"]).read_text(encoding="utf-8"))
            try:
                import pptx  # noqa: F401
                self.assertTrue(pathlib.Path(files["pptx"]).stat().st_size > 0)
            except ImportError:
                self.assertNotIn("pptx", files)


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
