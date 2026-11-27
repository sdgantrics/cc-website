"""The draft step keeps a verbatim quote and drops an invented one.

No API key. The model response is a recorded payload. sec comes from the
transcript match, not from the number the model sent.
"""

import os
import unittest

import editorial


SEGMENTS = [
    {"start_sec": 12, "text": "The concrete was still green when they loaded it."},
    {"start_sec": 48, "text": "We waited until the next morning."},
]

PAYLOAD = {
    "summary": "For supers who pour the slab and then drive on it.",
    "roles": ["Super"],
    "paths": ["running-the-job"],
    "tools": [],
    "related": [],
    "lessons": [
        {
            "id": "green",
            "headline": "Do not load concrete that is still green.",
            "what_it_cost": "The slab cracked.",
            "quote": "The concrete was still green when they loaded it.",
            "quote_speaker": "Ada",
            "quote_sec": 999,
            "the_move": "Wait overnight.",
            "roles": ["Super"],
        },
        {
            "id": "invented",
            "headline": "This was never said.",
            "what_it_cost": "Nothing.",
            "quote": "This sentence was never spoken on the show.",
            "quote_speaker": "Ada",
            "quote_sec": 48,
            "the_move": "Ignore it.",
            "roles": ["PM"],
        },
    ],
    "pull_quotes": [
        {"text": "We waited until the next morning.", "speaker": "Ada", "sec": 5},
        {"text": "A completely invented pull quote about robots.", "speaker": "Ada", "sec": 12},
    ],
}


class DraftQuoteTest(unittest.TestCase):
    def test_invented_quote_dropped_and_real_quote_keeps_transcript_sec(self):
        draft, log = editorial.apply_model_draft(PAYLOAD, SEGMENTS)
        print("LOG:")
        for line in log:
            print(line)

        self.assertEqual(len(draft["lessons"]), 1)
        lesson = draft["lessons"][0]
        self.assertEqual(lesson["id"], "green")
        self.assertEqual(lesson["quote_sec"], 12)
        self.assertNotEqual(lesson["quote_sec"], 999)

        self.assertEqual(len(draft["pull_quotes"]), 1)
        self.assertEqual(draft["pull_quotes"][0]["sec"], 48)
        self.assertNotEqual(draft["pull_quotes"][0]["sec"], 5)
        self.assertIn("next morning", draft["pull_quotes"][0]["text"])

        dropped = " ".join(log)
        self.assertIn("This sentence was never spoken", dropped)
        self.assertIn("invented pull quote", dropped)
        self.assertIn("DROPPED", dropped)
        self.assertNotIn("quote_sec: 999", str(draft))

    def test_missing_env_fails_clearly(self):
        saved = {name: os.environ.pop(name, None) for name in ("ANTHROPIC_API_KEY", "DRAFT_MODEL")}
        try:
            with self.assertRaises(SystemExit) as caught:
                editorial.draft_env()
            message = str(caught.exception)
            self.assertIn("ANTHROPIC_API_KEY", message)
            self.assertIn("DRAFT_MODEL", message)
            self.assertIn("does not call the API", message)
        finally:
            for name, value in saved.items():
                if value is not None:
                    os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
