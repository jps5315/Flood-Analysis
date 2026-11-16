import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from flood_ops.config import load_settings  # noqa: E402
from flood_ops.publish import _serialize_failure_summary  # noqa: E402
from flood_ops.validate import validate_inputs  # noqa: E402


class ValidationFieldContractTests(unittest.TestCase):
    def test_validate_inputs_returns_pipeline_and_overlay_fields(self):
        counts = {"aoi": 1, "flood_2016": 2, "flood_2017": 3, "flood_2018": 4, "parcels": 5}
        fields = {
            "aoi": ["OBJECTID"],
            "flood_2016": ["OBJECTID", "FLD_ZONE"],
            "flood_2017": ["OBJECTID", "FLD_ZONE"],
            "flood_2018": ["OBJECTID", "FLD_ZONE"],
            "parcels": ["OBJECTID", "parcel_id"],
        }
        arcpy = SimpleNamespace(
            Exists=lambda path: path in counts,
            Describe=lambda path: SimpleNamespace(shapeType="Polygon"),
            management=SimpleNamespace(
                GetCount=lambda path: [counts[path]]
            ),
            ListFields=lambda path: [
                SimpleNamespace(name=name) for name in fields[path]
            ],
        )
        flood_paths = ["flood_2016", "flood_2017", "flood_2018"]

        result = validate_inputs(
            arcpy,
            load_settings(),
            "aoi",
            flood_paths,
            "parcels",
            None,
            SimpleNamespace(info=lambda *args: None),
        )

        self.assertEqual(
            set(result),
            {
                "aoi_count",
                "flood_counts",
                "parcel_count",
                "building_count",
                "parcel_id_field",
                "flood_zone_field",
                "aoi_name_field",
                "building_id_field",
            },
        )
        self.assertEqual(result["flood_counts"], [2, 3, 4])
        self.assertEqual(result["parcel_id_field"], "parcel_id")
        self.assertEqual(result["flood_zone_field"], "FLD_ZONE")

    def test_failure_summary_fits_geodatabase_text_field(self):
        import json

        encoded = _serialize_failure_summary(
            {
                "error_type": "EXECUTION",
                "error_message": "Processing failed.",
                "next_steps": ["Review the ArcPy error."],
                "stack_trace": "trace line\n" * 400,
            },
            2000,
        )

        self.assertLessEqual(len(encoded), 2000)
        summary = json.loads(encoded)
        self.assertEqual(summary["error_type"], "EXECUTION")
        self.assertIn("Processing failed.", summary["error_message"])


if __name__ == "__main__":
    unittest.main()
