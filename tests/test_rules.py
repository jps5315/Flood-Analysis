import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from flood_ops.config import load_settings  # noqa: E402
from flood_ops.rules import apply_impact_rule, collapse_parcel_overlaps  # noqa: E402


class ImpactRuleTests(unittest.TestCase):
    def setUp(self):
        self.settings = load_settings()

    def test_below_all_thresholds_is_not_impacted(self):
        flag, note = apply_impact_rule(0.4, 0.3, 20.0, 10.0, 5.0, self.settings)
        self.assertEqual(flag, 0)
        self.assertEqual(note, "below_threshold")

    def test_cumulative_cross_sectional_threshold_flags_parcel(self):
        flag, note = apply_impact_rule(5.0, 3.0, 100.0, 600.0, 250.0, self.settings)
        self.assertEqual(flag, 1)
        self.assertIn("cumulative_cross_sectional_area_sf", note)

    def test_single_year_cross_sectional_threshold_flags_parcel(self):
        flag, note = apply_impact_rule(5.0, 3.0, 100.0, 50.0, 250.0, self.settings)
        self.assertEqual(flag, 1)
        self.assertIn("max_single_year_cross_sectional_area_sf", note)

    def test_cumulative_percent_threshold_flags_parcel(self):
        flag, note = apply_impact_rule(12.0, 3.0, 50.0, 10.0, 5.0, self.settings)
        self.assertEqual(flag, 1)
        self.assertIn("cumulative_overlap_pct", note)

    def test_single_year_percent_threshold_flags_parcel(self):
        flag, note = apply_impact_rule(5.0, 6.0, 50.0, 10.0, 5.0, self.settings)
        self.assertEqual(flag, 1)
        self.assertIn("max_single_year_overlap_pct", note)

    def test_compound_rule_both_conditions_fire(self):
        flag, note = apply_impact_rule(15.0, 8.0, 400.0, 600.0, 250.0, self.settings)
        self.assertEqual(flag, 1)
        self.assertIn("cumulative_overlap_pct", note)
        self.assertIn("max_single_year_overlap_pct", note)


class CollapseTests(unittest.TestCase):
    def test_multi_year_overlaps_aggregate_correctly(self):
        rows = [
            {
                "parcel_id": "A",
                "parcel_area_sf": 10000,
                "overlap_area_sf": 4000,
                "overlap_pct": 40.0,
                "cross_sectional_area_sf": 200.0,
                "flood_zone": "AE",
                "year": 2016,
            },
            {
                "parcel_id": "A",
                "parcel_area_sf": 10000,
                "overlap_area_sf": 7000,
                "overlap_pct": 70.0,
                "cross_sectional_area_sf": 350.0,
                "flood_zone": "AO",
                "year": 2017,
            },
            {
                "parcel_id": "A",
                "parcel_area_sf": 10000,
                "overlap_area_sf": 2000,
                "overlap_pct": 20.0,
                "cross_sectional_area_sf": 100.0,
                "flood_zone": "AE",
                "year": 2018,
            },
            {
                "parcel_id": "B",
                "parcel_area_sf": 5000,
                "overlap_area_sf": 500,
                "overlap_pct": 10.0,
                "cross_sectional_area_sf": 25.0,
                "flood_zone": "X",
                "year": 2016,
            },
        ]
        collapsed = {row["parcel_id"]: row for row in collapse_parcel_overlaps(rows)}
        self.assertEqual(len(collapsed), 2)
        # Parcel A: 4000+7000+2000 = 13000 cumulative, capped to 10000 (100%)
        self.assertEqual(collapsed["A"]["cumulative_overlap_area_sf"], 10000)
        self.assertEqual(collapsed["A"]["cumulative_overlap_pct"], 100.0)
        self.assertTrue(collapsed["A"]["overlap_capped"])
        self.assertEqual(collapsed["A"]["max_single_year_overlap_pct"], 70.0)
        self.assertEqual(collapsed["A"]["cumulative_cross_sectional_area_sf"], 650.0)
        self.assertEqual(collapsed["A"]["max_single_year_cross_sectional_area_sf"], 350.0)
        self.assertEqual(collapsed["A"]["years_with_flood_count"], 3)
        self.assertEqual(collapsed["A"]["flood_zone"], "AE|AO")
        # Parcel B: single year
        self.assertEqual(collapsed["B"]["cumulative_overlap_area_sf"], 500)
        self.assertEqual(collapsed["B"]["cumulative_overlap_pct"], 10.0)
        self.assertEqual(collapsed["B"]["max_single_year_overlap_pct"], 10.0)
        self.assertEqual(collapsed["B"]["cumulative_cross_sectional_area_sf"], 25.0)
        self.assertEqual(collapsed["B"]["max_single_year_cross_sectional_area_sf"], 25.0)
        self.assertEqual(collapsed["B"]["years_with_flood_count"], 1)


if __name__ == "__main__":
    unittest.main()
