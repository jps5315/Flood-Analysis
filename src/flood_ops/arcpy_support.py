from __future__ import annotations

from typing import Any

from .validate import ValidationError, require_arcpy


def field_map_type(arcpy, type_name: str):
    mapping = {
        "TEXT": "TEXT",
        "DATE": "DATE",
        "DOUBLE": "DOUBLE",
        "SHORT": "SHORT",
        "LONG": "LONG",
        "FLOAT": "FLOAT",
    }
    if type_name not in mapping:
        raise ValidationError(f"Unsupported schema field type: {type_name}")
    return mapping[type_name]


def add_schema_fields(arcpy, dataset: str, fields: list[dict[str, Any]]) -> None:
    existing = {f.name.lower() for f in arcpy.ListFields(dataset)}
    for field in fields:
        if field["name"].lower() in existing:
            continue
        kwargs = {
            "in_table": dataset,
            "field_name": field["name"],
            "field_type": field_map_type(arcpy, field["type"]),
            "field_alias": field.get("alias", field["name"]),
        }
        if field["type"] == "TEXT":
            kwargs["field_length"] = int(field.get("length", 255))
        arcpy.management.AddField(**kwargs)


def create_feature_class_from_schema(arcpy, gdb: str, name: str, spec: dict[str, Any], wkid: int) -> str:
    out_path = f"{gdb}\\{name}"
    sr = arcpy.SpatialReference(wkid)
    if spec["geometry_type"] == "TABLE":
        if arcpy.Exists(out_path):
            return out_path
        arcpy.management.CreateTable(gdb, name)
        add_schema_fields(arcpy, out_path, spec["fields"])
        return out_path
    if not arcpy.Exists(out_path):
        arcpy.management.CreateFeatureclass(
            gdb,
            name,
            spec["geometry_type"],
            spatial_reference=sr,
        )
        add_schema_fields(arcpy, out_path, spec["fields"])
    return out_path


def delete_run_rows(arcpy, dataset: str, run_id: str) -> None:
    """Idempotency: re-running the same run_id replaces that run, it does not duplicate it."""
    if not arcpy.Exists(dataset):
        return
    view = "run_rows_view"
    arcpy.management.MakeTableView(dataset, view)
    arcpy.management.SelectLayerByAttribute(view, "NEW_SELECTION", f"run_id = '{run_id}'")
    count = int(arcpy.management.GetCount(view)[0])
    if count:
        arcpy.management.DeleteRows(view)
    arcpy.management.Delete(view)


def project_to_client_crs(arcpy, in_dataset: str, out_dataset: str, wkid: int) -> str:
    desc = arcpy.Describe(in_dataset)
    in_wkid = None
    try:
        in_wkid = int(desc.spatialReference.factoryCode)
    except Exception:
        in_wkid = None
    if in_wkid == wkid:
        arcpy.management.CopyFeatures(in_dataset, out_dataset)
        return out_dataset
    arcpy.management.Project(in_dataset, out_dataset, arcpy.SpatialReference(wkid))
    return out_dataset


def repair_if_needed(arcpy, dataset: str, enabled: bool) -> None:
    if not enabled:
        return
    arcpy.management.RepairGeometry(dataset, "DELETE_NULL")


__all__ = [
    "require_arcpy",
    "add_schema_fields",
    "create_feature_class_from_schema",
    "delete_run_rows",
    "project_to_client_crs",
    "repair_if_needed",
]
