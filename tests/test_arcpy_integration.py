"""Optional ArcPy integration tests. Skipped on machines without Pro/Server Python."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    import arcpy  # type: ignore
except ImportError:
    arcpy = None


@unittest.skipIf(arcpy is None, "ArcPy is not installed in this Python")
class ArcPyWorkflowTests(unittest.TestCase):
    def test_sample_geojson_converts_and_runs(self):
        from flood_ops.pipeline import run_flood_impact

        geojson_dir = ROOT / "data" / "sample" / "geojson"
        self.assertTrue((geojson_dir / "parcels.geojson").is_file())
        scratch = Path(tempfile.mkdtemp(prefix="flood_ops_test_"))
        gdb = scratch / "in.gdb"
        arcpy.env.overwriteOutput = True
        arcpy.management.CreateFileGDB(str(scratch), "in.gdb")
        layers = {}
        for name in ("aoi", "flood", "parcels", "buildings"):
            raw = str(gdb / f"{name}_wgs84")
            projected = str(gdb / name)
            arcpy.conversion.JSONToFeatures(str(geojson_dir / f"{name}.geojson"), raw, "POLYGON")
            arcpy.management.Project(raw, projected, arcpy.SpatialReference(3083))
            layers[name] = projected
        result = run_flood_impact(
            aoi_path=layers["aoi"],
            flood_path=layers["flood"],
            parcels_path=layers["parcels"],
            buildings_path=layers["buildings"],
            output_workspace=str(scratch / "out"),
            scratch_folder=str(scratch / "scratch"),
            scenario_name="TEST_FEMA",
            aoi_name="Test AOI",
        )
        self.assertGreater(result["parcel_count"], 0)
        self.assertIn("latest_parcels", result["outputs"])
        self.assertTrue(Path(result["reports"]["csv"]).is_file())


if __name__ == "__main__":
    unittest.main()
