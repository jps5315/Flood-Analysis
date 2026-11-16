"""
REST API loader with pagination support for ArcGIS services.

This module handles loading data from ArcGIS REST services with automatic
pagination when record counts exceed the threshold (default 2000).
"""

import json
import requests
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class RestLoader:
    """Load data from ArcGIS REST services with pagination support."""

    def __init__(self, pagination_threshold: int = 2000, pagination_record_count: int = 2000, timeout: int = 60):
        """
        Initialize REST loader.

        Args:
            pagination_threshold: Use pagination if total records > this value
            pagination_record_count: Number of records per pagination cycle
            timeout: Request timeout in seconds
        """
        self.pagination_threshold = pagination_threshold
        self.pagination_record_count = pagination_record_count
        self.timeout = timeout

    def get_service_metadata(self, service_url: str) -> Dict:
        """
        Query service metadata to get total record count and MaxRecordCount.

        Args:
            service_url: ArcGIS REST service URL (e.g., .../FeatureServer/0)

        Returns:
            Dict with metadata including 'count' and 'maxRecordCount'
        """
        # Query metadata
        params = {
            'f': 'json'
        }

        try:
            response = requests.get(service_url, params=params, timeout=self.timeout)
            response.raise_for_status()
            metadata = response.json()

            return {
                'count': metadata.get('count', 0),
                'maxRecordCount': metadata.get('maxRecordCount', 1000),
                'name': metadata.get('name', 'unknown'),
                'description': metadata.get('description', '')
            }
        except requests.RequestException as e:
            logger.error(f"Failed to query service metadata for {service_url}: {e}")
            raise

    def query_total_count(self, service_url: str, where_clause: str = "1=1") -> int:
        """
        Query total record count for a service with optional where clause.

        Args:
            service_url: ArcGIS REST service URL
            where_clause: SQL where clause (default: 1=1 for all features)

        Returns:
            Total record count
        """
        params = {
            'where': where_clause,
            'returnCountOnly': 'true',
            'f': 'json'
        }

        try:
            response = requests.get(f"{service_url}/query", params=params, timeout=self.timeout)
            response.raise_for_status()
            result = response.json()
            return result.get('count', 0)
        except requests.RequestException as e:
            logger.error(f"Failed to query count for {service_url}: {e}")
            raise

    def query_features(self, service_url: str, where_clause: str = "1=1",
                       out_fields: str = "*", spatial_reference: Optional[int] = None,
                       geometry_filter: Optional[Dict] = None) -> Tuple[List[Dict], Dict]:
        """
        Query features from ArcGIS REST service with automatic pagination.

        Args:
            service_url: ArcGIS REST service URL
            where_clause: SQL where clause
            out_fields: Comma-separated field list (default: * for all)
            spatial_reference: Output CRS WKID (default: 4326)
            geometry_filter: Optional geometry filter dict (e.g., bbox)

        Returns:
            Tuple of (features list, pagination_info dict)
        """
        # First, get total count
        total_count = self.query_total_count(service_url, where_clause)

        pagination_info = {
            'total_count': total_count,
            'use_pagination': total_count > self.pagination_threshold,
            'pagination_cycles': 0,
            'records_per_cycle': self.pagination_record_count,
            'records_fetched': 0
        }

        if total_count == 0:
            logger.warning(f"Service {service_url} returned 0 records")
            return [], pagination_info

        # If count is small, single query is sufficient
        if total_count <= self.pagination_threshold:
            return self._single_query(service_url, where_clause, out_fields, spatial_reference, geometry_filter, pagination_info)

        # Otherwise, use pagination
        return self._paginated_query(service_url, where_clause, out_fields, spatial_reference, geometry_filter, pagination_info)

    def _single_query(self, service_url: str, where_clause: str, out_fields: str,
                     spatial_reference: Optional[int], geometry_filter: Optional[Dict],
                     pagination_info: Dict) -> Tuple[List[Dict], Dict]:
        """Single query without pagination."""
        params = {
            'where': where_clause,
            'outFields': out_fields,
            'returnGeometry': 'true',
            'f': 'json'
        }

        if spatial_reference:
            params['outSR'] = spatial_reference

        if geometry_filter:
            params.update(geometry_filter)

        try:
            response = requests.get(f"{service_url}/query", params=params, timeout=self.timeout)
            response.raise_for_status()
            result = response.json()

            features = result.get('features', [])
            pagination_info['records_fetched'] = len(features)
            pagination_info['pagination_cycles'] = 1

            logger.info(f"Single query fetched {len(features)} records (threshold: {self.pagination_threshold})")

            return features, pagination_info
        except requests.RequestException as e:
            logger.error(f"Failed to query features: {e}")
            raise

    def _paginated_query(self, service_url: str, where_clause: str, out_fields: str,
                        spatial_reference: Optional[int], geometry_filter: Optional[Dict],
                        pagination_info: Dict) -> Tuple[List[Dict], Dict]:
        """Paginated query with multiple cycles."""
        all_features = []
        offset = 0
        cycle = 0

        while True:
            params = {
                'where': where_clause,
                'outFields': out_fields,
                'returnGeometry': 'true',
                'resultOffset': offset,
                'resultRecordCount': self.pagination_record_count,
                'f': 'json'
            }

            if spatial_reference:
                params['outSR'] = spatial_reference

            if geometry_filter:
                params.update(geometry_filter)

            try:
                response = requests.get(f"{service_url}/query", params=params, timeout=self.timeout)
                response.raise_for_status()
                result = response.json()

                features = result.get('features', [])
                all_features.extend(features)

                cycle += 1
                pagination_info['pagination_cycles'] = cycle
                pagination_info['records_fetched'] = len(all_features)

                logger.info(f"Pagination cycle {cycle}: fetched {len(features)} records (offset {offset}, total so far: {len(all_features)})")

                # Check if we've fetched all records
                if len(features) < self.pagination_record_count:
                    # Last cycle
                    break

                offset += self.pagination_record_count

                # Safety check: don't infinite loop
                if offset > pagination_info['total_count'] + self.pagination_record_count:
                    logger.warning(f"Pagination exceeded expected count ({pagination_info['total_count']})")
                    break

            except requests.RequestException as e:
                logger.error(f"Failed to query features in pagination cycle {cycle}: {e}")
                raise

        # Validate we got the expected count
        if len(all_features) != pagination_info['total_count']:
            logger.warning(f"Pagination mismatch: expected {pagination_info['total_count']}, fetched {len(all_features)}")

        return all_features, pagination_info

    def save_to_geojson(self, features: List[Dict], output_path: Path, metadata: Optional[Dict] = None):
        """
        Save features to GeoJSON file.

        Args:
            features: List of feature dicts from ArcGIS REST
            output_path: Output GeoJSON file path
            metadata: Optional metadata to include in properties
        """
        geojson = {
            'type': 'FeatureCollection',
            'features': features
        }

        if metadata:
            geojson['metadata'] = metadata

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(geojson, f, indent=2)

        logger.info(f"Saved {len(features)} features to {output_path}")
