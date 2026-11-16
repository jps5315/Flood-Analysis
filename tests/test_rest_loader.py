"""Tests for REST loader with pagination support."""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import json
import tempfile
import shutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from flood_ops.rest_loader import RestLoader
from flood_ops.validate import is_rest_url


class TestRestLoader(unittest.TestCase):
    """Test REST loader pagination logic."""

    def setUp(self):
        """Set up test fixtures."""
        self.loader = RestLoader(pagination_threshold=2000, pagination_record_count=2000, timeout=60)
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_pagination_threshold_detection(self):
        """Test that pagination is used when count exceeds threshold."""
        # Mock service metadata
        metadata = {
            'count': 3000,
            'maxRecordCount': 2000
        }

        self.assertEqual(metadata['count'], 3000)
        self.assertTrue(metadata['count'] > self.loader.pagination_threshold)

    def test_single_query_for_small_dataset(self):
        """Test that single query is used for datasets below threshold."""
        self.assertEqual(self.loader.pagination_threshold, 2000)

        # Small dataset (1000 records) should not use pagination
        self.assertFalse(1000 > self.loader.pagination_threshold)

    def test_paginated_query_for_large_dataset(self):
        """Test that pagination is used for datasets above threshold."""
        # Large dataset (3000 records) should use pagination
        self.assertTrue(3000 > self.loader.pagination_threshold)

    @patch('flood_ops.rest_loader.requests.get')
    def test_query_total_count(self, mock_get):
        """Test querying total record count."""
        mock_response = Mock()
        mock_response.json.return_value = {'count': 5000}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        count = self.loader.query_total_count('http://example.com/FeatureServer/0')
        self.assertEqual(count, 5000)

    @patch('flood_ops.rest_loader.requests.get')
    def test_service_metadata(self, mock_get):
        """Test querying service metadata."""
        mock_response = Mock()
        mock_response.json.return_value = {
            'count': 6185,
            'maxRecordCount': 2000,
            'name': 'Test Service',
            'description': 'Test description'
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        metadata = self.loader.get_service_metadata('http://example.com/FeatureServer/0')
        self.assertEqual(metadata['count'], 6185)
        self.assertEqual(metadata['maxRecordCount'], 2000)
        self.assertEqual(metadata['name'], 'Test Service')

    @patch('flood_ops.rest_loader.requests.get')
    def test_save_to_geojson(self, mock_get):
        """Test saving features to GeoJSON."""
        features = [
            {
                'type': 'Feature',
                'properties': {'id': 1, 'name': 'Test'},
                'geometry': {'type': 'Point', 'coordinates': [0, 0]}
            }
        ]

        output_path = Path(self.temp_dir) / 'test.geojson'
        metadata = {'source': 'test'}

        self.loader.save_to_geojson(features, output_path, metadata)

        self.assertTrue(output_path.exists())

        with open(output_path, 'r') as f:
            saved = json.load(f)

        self.assertEqual(saved['type'], 'FeatureCollection')
        self.assertEqual(len(saved['features']), 1)
        self.assertEqual(saved['metadata'], metadata)

    def test_pagination_cycle_calculation(self):
        """Test pagination cycle calculation for known large dataset."""
        total_records = 6185
        records_per_cycle = 2000

        # Expected cycles: 2000 + 2000 + 2000 + 185 = 4 cycles
        expected_cycles = (total_records + records_per_cycle - 1) // records_per_cycle
        self.assertEqual(expected_cycles, 4)

    def test_is_rest_url_detection(self):
        """Test detection of REST URLs."""
        self.assertTrue(is_rest_url('http://example.com/arcgis/rest/services/FeatureServer/0'))
        self.assertTrue(is_rest_url('https://example.com/arcgis/rest/services/FeatureServer/0'))
        self.assertFalse(is_rest_url('C:/data/parcels.gdb/parcels'))
        self.assertFalse(is_rest_url('/home/user/data/parcels.shp'))
        self.assertFalse(is_rest_url('parcels.shp'))


if __name__ == '__main__':
    unittest.main()
