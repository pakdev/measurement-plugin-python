"""Measurement service metadata classes and enums."""

from __future__ import annotations

import enum
from pathlib import Path
from typing import NamedTuple

from ni_measurement_plugin_sdk_service._internal.stubs.ni.measurementlink.discovery.v1 import (
    discovery_service_pb2,
)


class MeasurementInfo(NamedTuple):
    """A named tuple providing information about a measurement."""

    display_name: str
    """The user visible name of the measurement."""

    version: str
    """The current version of the measurement."""

    ui_file_paths: list[Path]
    """Absolute paths to user interface files for the measurement (e.g. ``.measui`` or ``.vi``
    files)."""


class ServiceInfo(NamedTuple):
    """A named tuple providing information about a registered service.

    This class is used with the NI Discovery Service when registering and enumerating services.
    """

    service_class: str
    """"The "class" of a service. The value of this field should be unique for all services.
    In effect, the ``.proto`` service declaration defines the interface, and this field
    defines a class or concrete type of the interface."""

    description_url: str
    """The URL of a web page that provides a description of the service."""

    provided_interfaces: list[str] = ["ni.measurementlink.measurement.v1.MeasurementService"]
    """The service interfaces provided by the service. These are gRPC full names for the service."""

    annotations: dict[str, str] = {}
    """Represents a set of annotations on the service.

    Well-known annotations:

    - Description
       - Key: "ni/service.description"
          - Expected format: string
          - Example: "Measure inrush current with a shorted load and validate results against
            configured limits."
    - Collection
       - Key: "ni/service.collection"
          - Expected format: "." delimited namespace/hierarchy case-insensitive string
          - Example: "CurrentTests.Inrush"
    - Tags
        - Key: "ni/service.tags"
           - Expected format: serialized JSON string of an array of strings
           - Example: "[\"powerup\", \"current\"]"
    """

    display_name: str = ""
    """The service display name for clients to display to users."""

    versions: list[str] = []
    """The list of versions associated with this service in
     the form major.minor.build[.revision] (e.g. 1.0.0)."""

    @classmethod
    def _from_grpc(cls, other: discovery_service_pb2.ServiceDescriptor) -> ServiceInfo:
        return ServiceInfo(
            service_class=other.service_class,
            description_url=other.description_url,
            provided_interfaces=list(other.provided_interfaces),
            annotations=dict(other.annotations),
            display_name=other.display_name,
            versions=list(other.versions),
        )


class TypeSpecialization(enum.Enum):
    """Enum that represents the type specializations for measurement parameters."""

    NoType = ""
    Pin = "pin"
    Path = "path"
    Enum = "enum"
    IOResource = "ioresource"


class DataType(enum.Enum):
    """Enum that represents the supported data types."""

    Int32 = 0
    Int64 = 1
    UInt32 = 2
    UInt64 = 3
    Float = 4
    Double = 5
    Boolean = 6
    String = 7
    Pin = 8
    Path = 9
    Enum = 10
    DoubleXYData = 11
    IOResource = 12
    Double2DArray = 13
    String2DArray = 14

    Int32Array1D = 100
    Int64Array1D = 101
    UInt32Array1D = 102
    UInt64Array1D = 103
    FloatArray1D = 104
    DoubleArray1D = 105
    BooleanArray1D = 106
    StringArray1D = 107
    PinArray1D = 108
    PathArray1D = 109
    EnumArray1D = 110
    DoubleXYDataArray1D = 111
    IOResourceArray1D = 112


class MonikerType(enum.Enum):
    """Enum that represents the moniker types for measurement inputs/outputs."""

    ScalarData = enum.auto()
    ScalarArray = enum.auto()
    String2DArray = enum.auto()
    Double2DArray = enum.auto()
    DoubleXYData = enum.auto()
    DoubleAnalogWaveform = enum.auto()

    def to_url(self) -> str:
        if self == MonikerType.ScalarData:
            return "type.googleapis.com/ni.measurements.data.v1.ScalarData"
        elif self == MonikerType.ScalarArray:
            return "type.googleapis.com/ni.measurements.data.v1.ScalarArray"
        elif self == MonikerType.String2DArray:
            return "type.googleapis.com/ni.protobuf.types.String2DArray"
        elif self == MonikerType.Double2DArray:
            return "type.googleapis.com/ni.protobuf.types.Double2DArray"
        elif self == MonikerType.DoubleXYData:
            return "type.googleapis.com/ni.protobuf.types.DoubleXYData"
        elif self == MonikerType.DoubleAnalogWaveform:
            return "type.googleapis.com/ni.protobuf.types.DoubleAnalogWaveform"
        else:
            raise ValueError(f"Unsupported MonikerType: {self}")
