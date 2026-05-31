"""
Unit tests for composition_planner pure functions (stdlib unittest only).

Covers:
- clamp_plan_sections
- _lenient_json_parse
- finalize_plan

Run via: python3 -m unittest discover tests
"""

import json
import unittest

from composition_planner import (
    clamp_plan_sections,
    _lenient_json_parse,
    finalize_plan,
    MAX_SECTION_MS,
)


class TestClampPlanSections(unittest.TestCase):
    """Test clamp_plan_sections splits long sections, preserves total duration, leaves short ones alone, never crashes on bad input."""

    def _make_plan(self, durations_ms, name_prefix="Sec"):
        return {
            "positive_global_styles": ["ambient"],
            "negative_global_styles": ["drums"],
            "sections": [
                {
                    "section_name": f"{name_prefix} {i+1}",
                    "positive_local_styles": ["soft pads"],
                    "negative_local_styles": ["vocals"],
                    "duration_ms": d,
                }
                for i, d in enumerate(durations_ms)
            ],
        }

    def test_short_sections_untouched(self):
        plan = self._make_plan([30000, 45000, 60000])
        out = clamp_plan_sections(plan)
        self.assertIsNotNone(out)
        self.assertEqual(len(out["sections"]), 3)
        self.assertEqual([s["duration_ms"] for s in out["sections"]], [30000, 45000, 60000])
        self.assertEqual(sum(s["duration_ms"] for s in out["sections"]), 135000)
        # Original styles preserved
        self.assertIn("soft pads", out["sections"][0]["positive_local_styles"])

    def test_long_section_gets_split_and_total_preserved(self):
        # 300s total in one section > 120s -> must split
        plan = self._make_plan([300000])
        out = clamp_plan_sections(plan)
        self.assertIsNotNone(out)
        durs = [s["duration_ms"] for s in out["sections"]]
        self.assertEqual(sum(durs), 300000, "total duration must be preserved exactly")
        self.assertTrue(all(d <= MAX_SECTION_MS for d in durs), "all sections must be <= 120000ms")
        self.assertGreater(len(out["sections"]), 1, "long section must be split")
        # Names should indicate splits
        self.assertIn("(1/", out["sections"][0]["section_name"])
        # Styles copied to pieces
        self.assertEqual(out["sections"][0]["positive_local_styles"], ["soft pads"])

    def test_multiple_long_sections_and_mixed(self):
        plan = self._make_plan([250000, 30000, 180000])
        out = clamp_plan_sections(plan)
        durs = [s["duration_ms"] for s in out["sections"]]
        self.assertEqual(sum(durs), 250000 + 30000 + 180000)
        self.assertTrue(all(d <= MAX_SECTION_MS for d in durs))
        self.assertEqual(len(out["sections"]), 6)  # 250k -> 3 parts (ceil(250/120)), 30k->1, 180k->2

    def test_exact_multiple(self):
        plan = self._make_plan([240000])  # exactly 2*120k
        out = clamp_plan_sections(plan)
        durs = [s["duration_ms"] for s in out["sections"]]
        self.assertEqual(durs, [120000, 120000])
        self.assertEqual(sum(durs), 240000)

    def test_empty_and_odd_inputs_do_not_crash(self):
        # None
        self.assertIsNone(clamp_plan_sections(None))
        # Not a dict
        self.assertEqual(clamp_plan_sections("garbage"), "garbage")
        self.assertEqual(clamp_plan_sections(123), 123)
        # Dict but no sections key / bad type
        self.assertEqual(clamp_plan_sections({}), {})
        self.assertEqual(clamp_plan_sections({"foo": 1}), {"foo": 1})
        self.assertEqual(clamp_plan_sections({"sections": None}), {"sections": None})
        self.assertEqual(clamp_plan_sections({"sections": "notlist"}), {"sections": "notlist"})
        # Empty list
        p = {"sections": []}
        out = clamp_plan_sections(p)
        self.assertEqual(out["sections"], [])
        # Bad duration values (kept as-is for non-splitting case; must not crash)
        p = {"sections": [{"duration_ms": "notint", "section_name": "x"}]}
        out = clamp_plan_sections(p)
        self.assertEqual(len(out["sections"]), 1)
        self.assertEqual(out["sections"][0]["duration_ms"], "notint")  # original kept
        # Missing duration_ms key (original section kept verbatim for <= case; no crash)
        p = {"sections": [{"section_name": "no dur"}]}
        out = clamp_plan_sections(p)
        self.assertEqual(len(out["sections"]), 1)
        self.assertNotIn("duration_ms", out["sections"][0])  # absent in input, hence in output
        # Custom max_ms
        p = self._make_plan([100000])
        out = clamp_plan_sections(p, max_ms=50000)
        self.assertEqual(len(out["sections"]), 2)

    def test_idempotent_and_preserves_other_fields(self):
        plan = self._make_plan([30000])
        plan["extra"] = "value"
        out1 = clamp_plan_sections(plan)
        out2 = clamp_plan_sections(out1)
        self.assertEqual(out1, out2)
        self.assertEqual(out1.get("extra"), "value")


class TestLenientJsonParse(unittest.TestCase):
    """Test _lenient_json_parse handles valid, truncated (salvageable), and garbage input."""

    def test_valid_json_parses(self):
        good = json.dumps({
            "positive_global_styles": ["a"],
            "negative_global_styles": ["b"],
            "sections": [
                {"section_name": "Intro", "positive_local_styles": ["x"], "negative_local_styles": [], "duration_fraction": 0.5},
                {"section_name": "Outro", "positive_local_styles": ["y"], "negative_local_styles": [], "duration_fraction": 0.5},
            ]
        })
        data = _lenient_json_parse(good)
        self.assertIsInstance(data, dict)
        self.assertEqual(len(data.get("sections", [])), 2)
        self.assertIn("positive_global_styles", data)

    def test_valid_with_markdown_fences(self):
        fenced = '```json\n{"sections": [{"section_name": "A", "duration_fraction": 1.0}]}\n```'
        data = _lenient_json_parse(fenced)
        self.assertIsNotNone(data)
        self.assertEqual(data["sections"][0]["section_name"], "A")

    def test_truncated_json_still_returns_dict_with_complete_sections(self):
        # Simulate Claude truncation mid-response: full sections 0 and 1, cut during section 2
        truncated = (
            '{"positive_global_styles": ["ambient"], "negative_global_styles": ["drums"], '
            '"sections": ['
            '{"section_name": "Bed", "positive_local_styles": ["pads"], "negative_local_styles": ["vocals"], "duration_fraction": 0.3},'
            '{"section_name": "Lead enters", "positive_local_styles": ["cello"], "negative_local_styles": [], "duration_fraction": 0.4},'
            '{"section_name": "Full'  # cut here, mid-string even
        )
        data = _lenient_json_parse(truncated)
        self.assertIsNotNone(data, "salvage must succeed for truncated mid-section")
        self.assertIsInstance(data, dict)
        secs = data.get("sections", [])
        self.assertGreaterEqual(len(secs), 2, "must keep the complete sections before the truncation point")
        # The last kept section must be fully parseable (no partial objects)
        self.assertIn("Lead enters", [s.get("section_name") for s in secs])

    def test_truncated_various_cut_points(self):
        # Cut right after a complete section object
        cut_after_complete = '{"sections": [{"section_name": "Only", "duration_fraction": 1.0}]'
        data = _lenient_json_parse(cut_after_complete)
        self.assertIsNotNone(data)
        self.assertEqual(len(data.get("sections", [])), 1)

    def test_garbage_returns_none(self):
        self.assertIsNone(_lenient_json_parse(""))
        self.assertIsNone(_lenient_json_parse("   "))
        self.assertIsNone(_lenient_json_parse("not json at all"))
        self.assertIsNone(_lenient_json_parse("{"))
        self.assertIsNone(_lenient_json_parse("[1,2,3"))  # incomplete JSON (array cut off) -> salvage fails -> None
        self.assertIsNone(_lenient_json_parse('{"foo": "bar"'))  # incomplete, no closing that works for sections
        self.assertIsNone(_lenient_json_parse("```python\ndef foo(): pass\n```"))  # wrong language, not json


class TestFinalizePlan(unittest.TestCase):
    """Test finalize_plan rescales section durations to exactly match requested total."""

    def test_rescales_durations_to_exact_total(self):
        plan = {
            "positive_global_styles": ["g1", "g2"],
            "negative_global_styles": ["n1"],
            "sections": [
                {"section_name": "A", "positive_local_styles": ["p1"], "negative_local_styles": ["n1"], "duration_ms": 10000},
                {"section_name": "B", "positive_local_styles": ["p2"], "negative_local_styles": [], "duration_ms": 20000},
            ],
        }
        out = finalize_plan(plan, 600000)  # 10 min target
        self.assertIsNotNone(out)
        durs = [s["duration_ms"] for s in out["sections"]]
        self.assertEqual(sum(durs), 600000, "rescaled durations must sum exactly to requested total")
        self.assertGreaterEqual(min(durs), 3000)  # code enforces min 3000 except possibly tiny cases

    def test_last_section_takes_remainder(self):
        plan = {"sections": [
            {"duration_ms": 1},
            {"duration_ms": 1},
            {"duration_ms": 1},
        ]}
        out = finalize_plan(plan, 10007)
        durs = [s["duration_ms"] for s in out["sections"]]
        self.assertEqual(sum(durs), 10007)
        self.assertEqual(durs[-1], 10007 - durs[0] - durs[1])  # remainder logic

    def test_bad_input_returns_none(self):
        self.assertIsNone(finalize_plan(None, 60000))
        self.assertIsNone(finalize_plan({}, 60000))
        self.assertIsNone(finalize_plan({"sections": []}, 60000))
        self.assertIsNone(finalize_plan({"sections": None}, 60000))

    def test_produces_full_elevenlabs_shape(self):
        plan = {"sections": [{"section_name": "X", "positive_local_styles": ["a", "b", "c", "d", "e", "f", "g", "h", "i"], "duration_ms": 12345}]}
        out = finalize_plan(plan, 30000)
        self.assertIn("positive_global_styles", out)
        self.assertIn("negative_global_styles", out)
        sec = out["sections"][0]
        self.assertIn("lines", sec)
        self.assertEqual(sec["lines"], [])
        self.assertEqual(sec["duration_ms"], 30000)
        # Truncation of long lists
        self.assertEqual(len(sec["positive_local_styles"]), 8)

    def test_zero_or_negative_durs_handled(self):
        plan = {"sections": [{"duration_ms": 0}, {"duration_ms": -5}]}
        out = finalize_plan(plan, 120000)
        durs = [s["duration_ms"] for s in out["sections"]]
        self.assertEqual(sum(durs), 120000)
        self.assertTrue(all(d >= 3000 for d in durs))


if __name__ == "__main__":
    unittest.main()
