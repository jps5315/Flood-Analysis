import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from flood_ops.config import load_schema, load_settings, project_root  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_project_root_is_repo(self):
        self.assertTrue((project_root() / "config" / "settings.json").is_file())

    def test_settings_load_and_crs(self):
        settings = load_settings()
        self.assertEqual(settings["client_crs"]["wkid"], 3083)
        self.assertEqual(settings["impact_rule"]["overlay_method"], "vector_raster_hybrid")
        self.assertEqual(settings["impact_rule"]["definition"], "cumulative_compound_3d")
        self.assertEqual(settings["impact_rule"]["historical_years"], [2016, 2017, 2018])
        self.assertEqual(settings["impact_rule"]["min_cumulative_cross_sectional_area_sf"], 500.0)
        self.assertEqual(settings["impact_rule"]["min_single_year_cross_sectional_area_sf"], 200.0)

    def test_schema_contract_has_required_fields(self):
        schema = load_schema()
        self.assertEqual(schema["version"], "3.0.0")
        names = {f["name"] for f in schema["feature_classes"]["ImpactedParcels"]["fields"]}
        for required in (
            "run_id",
            "parcel_id",
            "overlap_pct",
            "cumulative_overlap_pct",
            "max_single_year_overlap_pct",
            "cross_sectional_area_sf",
            "cumulative_cross_sectional_area_sf",
            "max_single_year_cross_sectional_area_sf",
            "years_with_flood_count",
            "impact_flag",
            "building_count",
        ):
            self.assertIn(required, names)
        # Check FloodImpact_Runs has new fields
        runs_fields = {f["name"] for f in schema["feature_classes"]["FloodImpact_Runs"]["fields"]}
        for required in ("version_id", "input_metadata", "result_summary", "failure_summary"):
            self.assertIn(required, runs_fields)
        # Check StepLog exists
        self.assertIn("StepLog", schema["feature_classes"])


if __name__ == "__main__":
    unittest.main()
