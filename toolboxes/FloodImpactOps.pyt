# -*- coding: utf-8 -*-
"""Python toolbox UI for Houston Flood Impact Ops."""
import os
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(PROJECT_ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from flood_ops.config import load_settings  # noqa: E402
from flood_ops.logging_setup import configure_logging  # noqa: E402
from flood_ops.pipeline import run_flood_impact  # noqa: E402
from flood_ops.validate import (  # noqa: E402
    ValidationError,
    require_arcpy,
    validate_inputs,
)


class Toolbox(object):
    def __init__(self):
        self.label = "Houston Flood Impact Ops"
        self.alias = "floodops"
        self.tools = [ValidateFloodInputs, RunFloodImpact]


class ValidateFloodInputs(object):
    def __init__(self):
        self.label = "1. Validate flood impact inputs"
        self.description = (
            "Check geometry, feature counts, and required fields before analysis."
        )
        self.canRunInBackground = True
        self.category = "Quality control"

    def getParameterInfo(self):
        return _input_parameters(include_outputs=False)

    def execute(self, parameters, messages):
        arcpy = require_arcpy()
        settings = load_settings()
        scratch = getattr(arcpy.env, "scratchFolder", None) or tempfile.gettempdir()
        logger = configure_logging(Path(scratch), "validate", messages)
        values = _parameter_values(parameters)
        info = validate_inputs(
            arcpy,
            settings,
            values["aoi"],
            values["floods"],
            values["parcels"],
            values["buildings"],
            logger,
        )
        messages.addMessage("Inputs passed validation.")
        messages.addMessage(str(info))


class RunFloodImpact(object):
    def __init__(self):
        self.label = "2. Run flood impact"
        self.description = (
            "Analyze flood impact by parcel and write geodatabase outputs and reports."
        )
        self.canRunInBackground = True
        self.category = "Operations"

    def getParameterInfo(self):
        return _input_parameters(include_outputs=True)

    def execute(self, parameters, messages):
        values = _parameter_values(parameters)
        try:
            result = run_flood_impact(
                aoi_path=values["aoi"],
                flood_paths=values["floods"],
                parcels_path=values["parcels"],
                buildings_path=values["buildings"],
                depth_raster_paths=values["depth_rasters"],
                output_workspace=parameters[11].valueAsText,
                scratch_folder=parameters[12].valueAsText,
                scenario_name=values["scenario"],
                aoi_name=values["aoi_name"],
                layout_aprx=parameters[13].valueAsText,
                arcpy_messages=messages,
            )
        except ValidationError as exc:
            messages.addErrorMessage(str(exc))
            raise

        messages.addMessage(
            "Succeeded. run_id={run_id} impacted={impacted_count}/{parcel_count}".format(
                **result
            )
        )
        messages.addMessage(
            "Production GDB: {0}".format(result["outputs"]["production_gdb"])
        )
        for kind, path in result["reports"].items():
            messages.addMessage("{0}: {1}".format(kind, path))
        parameters[14].value = result["outputs"]["latest_parcels"]


def _input_parameters(include_outputs):
    import arcpy

    aoi = _feature_parameter(
        arcpy,
        "Area of interest (watershed or incident polygon)",
        "aoi",
        "Required",
    )
    flood_2016 = _feature_parameter(
        arcpy, "Flood scenario - 2016", "flood_2016", "Required"
    )
    flood_2017 = _feature_parameter(
        arcpy, "Flood scenario - 2017", "flood_2017", "Required"
    )
    flood_2018 = _feature_parameter(
        arcpy, "Flood scenario - 2018", "flood_2018", "Required"
    )
    parcels = _feature_parameter(arcpy, "Parcels", "parcels", "Required")
    buildings = _feature_parameter(
        arcpy,
        "Building footprints (optional)",
        "buildings",
        "Optional",
    )
    buildings.category = "Inputs"

    depth_2016 = _raster_parameter(arcpy, "Flood depth raster - 2016", "depth_2016")
    depth_2017 = _raster_parameter(arcpy, "Flood depth raster - 2017", "depth_2017")
    depth_2018 = _raster_parameter(arcpy, "Flood depth raster - 2018", "depth_2018")

    scenario = arcpy.Parameter(
        displayName="Scenario name",
        name="scenario_name",
        datatype="GPString",
        parameterType="Required",
        direction="Input",
        category="Run",
    )
    scenario.value = "Cumulative_3Year_Flood"

    aoi_name = arcpy.Parameter(
        displayName="AOI name",
        name="aoi_name",
        datatype="GPString",
        parameterType="Optional",
        direction="Input",
        category="Run",
    )
    aoi_name.value = "AOI"

    parameters = [
        aoi,
        flood_2016,
        flood_2017,
        flood_2018,
        parcels,
        buildings,
        depth_2016,
        depth_2017,
        depth_2018,
        scenario,
        aoi_name,
    ]

    if include_outputs:
        output = arcpy.Parameter(
            displayName="Production workspace (folder or file geodatabase)",
            name="output_workspace",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
            category="Outputs",
        )
        scratch = arcpy.Parameter(
            displayName="Scratch folder",
            name="scratch_folder",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input",
            category="Outputs",
        )
        aprx = arcpy.Parameter(
            displayName="Optional Pro project with Map Series layout",
            name="layout_aprx",
            datatype="DEFile",
            parameterType="Optional",
            direction="Input",
            category="Outputs",
        )
        aprx.filter.list = ["aprx"]
        latest = arcpy.Parameter(
            displayName="Impacted parcels (latest)",
            name="latest_parcels",
            datatype="DEFeatureClass",
            parameterType="Derived",
            direction="Output",
            category="Outputs",
        )
        parameters.extend([output, scratch, aprx, latest])

    return parameters


def _feature_parameter(arcpy, display_name, name, parameter_type):
    parameter = arcpy.Parameter(
        displayName=display_name,
        name=name,
        datatype="GPFeatureLayer",
        parameterType=parameter_type,
        direction="Input",
        category="Inputs",
    )
    parameter.filter.list = ["Polygon"]
    return parameter


def _raster_parameter(arcpy, display_name, name):
    return arcpy.Parameter(
        displayName=display_name,
        name=name,
        datatype="GPRasterLayer",
        parameterType="Optional",
        direction="Input",
        category="Inputs",
    )


def _parameter_values(parameters):
    depth_rasters = [
        parameters[6].valueAsText if parameters[6].value else None,
        parameters[7].valueAsText if parameters[7].value else None,
        parameters[8].valueAsText if parameters[8].value else None,
    ]
    return {
        "aoi": parameters[0].valueAsText,
        "floods": [
            parameters[1].valueAsText,
            parameters[2].valueAsText,
            parameters[3].valueAsText,
        ],
        "parcels": parameters[4].valueAsText,
        "buildings": parameters[5].valueAsText,
        "depth_rasters": depth_rasters if any(depth_rasters) else [],
        "scenario": parameters[9].valueAsText,
        "aoi_name": parameters[10].valueAsText or "AOI",
    }
