"""gRPC servicers for each version of the measurement service interface."""

from __future__ import annotations

import collections.abc
import contextlib
import inspect
import pathlib
import warnings
import weakref
from collections.abc import Generator
from contextvars import ContextVar
from typing import Any, AsyncGenerator, AsyncIterable, Callable

import grpc
from google.protobuf import any_pb2

from ni_measurement_plugin_sdk_service._internal.parameter import decoder, encoder
from ni_measurement_plugin_sdk_service._internal.parameter.metadata import ParameterMetadata
from ni_measurement_plugin_sdk_service._internal.stubs.ni.measurementlink.measurement.v3 import (
    measurement_service_pb2 as v3_measurement_service_pb2,
)
from ni_measurement_plugin_sdk_service._internal.stubs.ni.measurementlink.measurement.v3 import (
    measurement_service_pb2_grpc as v3_measurement_service_pb2_grpc,
)
from ni_measurement_plugin_sdk_service.measurement import WrongMessageTypeWarning
from ni_measurement_plugin_sdk_service.measurement.info import MeasurementInfo, ServiceInfo
from ni_measurement_plugin_sdk_service.session_management import PinMapContext


class MeasurementServiceContext:
    """Accessor for the measurement service's context-local state."""

    def __init__(
        self,
        grpc_context: grpc.ServicerContext,
        pin_map_context: PinMapContext,
        owner: weakref.ReferenceType[object] | None,
    ) -> None:
        """Initialize the measurement service context."""
        self._grpc_context = grpc_context
        self._pin_map_context = pin_map_context
        self._is_complete = False
        self._owner = owner

    def mark_complete(self) -> None:
        """Mark the current RPC as complete."""
        self._is_complete = True

    @property
    def grpc_context(self) -> grpc.ServicerContext:
        """Get the context for the RPC."""
        return self._grpc_context

    @property
    def owner(self) -> object:
        """The owner of the server (e.g. measurement service)."""
        if self._owner is None:
            return None
        return self._owner()  # dereference weak ref

    @property
    def pin_map_context(self) -> PinMapContext:
        """Get the pin map context for the RPC."""
        return self._pin_map_context

    def add_cancel_callback(self, cancel_callback: Callable[[], None]) -> None:
        """Add a callback that is invoked when the RPC is canceled."""

        def grpc_callback() -> None:
            if not self._is_complete:
                cancel_callback()

        self._grpc_context.add_callback(grpc_callback)

    def cancel(self) -> None:
        """Cancel the RPC."""
        if not self._is_complete:
            self._grpc_context.cancel()

    @property
    def time_remaining(self) -> float:
        """Get the time remaining for the RPC."""
        return self._grpc_context.time_remaining()

    def abort(self, code: grpc.StatusCode, details: str) -> None:
        """Aborts the RPC."""
        try:
            self._grpc_context.abort(code, details)
        except Exception as e:
            # If gRPC raises an empty exception, replace it with an RpcError.
            # This allows our logging interceptors to query the code/details.
            if type(e) is Exception:
                raise CustomRpcError(code, details) from e
            raise


class CustomRpcError(grpc.RpcError):
    """A custom exception class for handling gRPC RPC errors.

    gRPC's built-in RpcError is not directly configurable in Python, so this class
    enables the creation of custom RPC errors with specific error codes.
    """

    def __init__(self, code: grpc.StatusCode, details: str) -> None:
        """Initialize a CustomRpcError instance."""
        self._code = code
        self._details = details

    def code(self) -> grpc.StatusCode:
        """Get the gRPC status code."""
        return self._code

    def details(self) -> str:
        """Get the gRPC status details."""
        return self._details


measurement_service_context: ContextVar[MeasurementServiceContext] = ContextVar(
    "measurement_service_context"
)


def _get_mapping_by_parameter_name(
    mapping_by_id: dict[int, Any],
    request_iterator: AsyncIterable[v3_measurement_service_pb2.MeasureRequest],
    context: grpc.aio.ServicerContext,
    measure_function: Callable[[], None],
) -> dict[str, Any]:
    """Transform a mapping by id into a mapping by parameter name (i.e. kwargs)."""
    signature = inspect.signature(measure_function)
    mapping_by_variable_name = {}

    found_request_iterator, found_context = False, False
    for parameter in signature.parameters.values():
        if "MeasureRequest" in str(parameter.annotation):
            mapping_by_variable_name[parameter.name] = request_iterator
            found_request_iterator = True
        elif "ServicerContext" in str(parameter.annotation):
            mapping_by_variable_name[parameter.name] = context
            found_context = True

    config_i = 1
    for i, parameter in enumerate(signature.parameters.values(), start=1):
        if not found_request_iterator and i == 1:
            # Request iterator should be the first parameter if it doesn't have a type
            mapping_by_variable_name[parameter.name] = request_iterator
        elif not found_context and i == len(signature.parameters):
            # Context should be the last parameter if it doesn't have a type
            mapping_by_variable_name[parameter.name] = context
        else:
            mapping_by_variable_name[parameter.name] = mapping_by_id[config_i]
            config_i += 1

    return mapping_by_variable_name


def frame_metadata_dict(
    parameter_list: list[ParameterMetadata],
) -> dict[int, ParameterMetadata]:
    """Create a metadata dictionary."""
    metadata_dict = {}
    for i, parameter in enumerate(parameter_list, start=1):
        metadata_dict[i] = parameter
    return metadata_dict


class MeasurementServiceServicerV3(v3_measurement_service_pb2_grpc.MeasurementServiceServicer):
    """Measurement v3 servicer."""

    def __init__(
        self,
        measurement_info: MeasurementInfo,
        configuration_parameter_list: list[ParameterMetadata],
        input_parameters: dict[str, str],
        output_parameters: dict[str, str],
        measure_function: Callable,
        owner: object,
        service_info: ServiceInfo,
    ) -> None:
        """Initialize the measurement v3 servicer."""
        super().__init__()
        self._configuration_metadata = frame_metadata_dict(configuration_parameter_list)
        self._measurement_info = measurement_info
        self._measure_function = measure_function
        self._owner = weakref.ref(owner) if owner is not None else None  # avoid reference cycle
        self._service_info = service_info
        self._configuration_parameters_message_type = service_info.service_class + ".Configurations"
        self._input_parameters = input_parameters
        self._output_parameters = output_parameters

    def GetMetadata(  # noqa: N802 - function name should be lowercase
        self, _: v3_measurement_service_pb2.GetMetadataRequest, __: grpc.ServicerContext
    ) -> v3_measurement_service_pb2.GetMetadataResponse:
        """RPC API to get measurement metadata."""
        measurement_details = v3_measurement_service_pb2.MeasurementDetails(
            display_name=self._measurement_info.display_name,
            version=self._measurement_info.version,
        )

        measurement_signature = v3_measurement_service_pb2.MeasurementSignature(
            configuration_parameters_message_type=self._configuration_parameters_message_type,
            inputs=[
                v3_measurement_service_pb2.DataValueMetadata(name=name, type_url=type_url)
                for name, type_url in self._input_parameters
            ],
            outputs=[
                v3_measurement_service_pb2.DataValueMetadata(name=name, type_url=type_url)
                for name, type_url in self._output_parameters
            ],
        )

        for field_number, configuration_metadata in self._configuration_metadata.items():
            configuration_parameter = v3_measurement_service_pb2.ConfigurationParameter(
                field_number=field_number,
                name=configuration_metadata.display_name,
                repeated=configuration_metadata.repeated,
                type=configuration_metadata.type,
                annotations=configuration_metadata.annotations,
                message_type=configuration_metadata.message_type,
            )
            measurement_signature.configuration_parameters.append(configuration_parameter)

        measurement_signature.configuration_defaults.value = encoder.serialize_default_values(
            self._configuration_metadata, self._configuration_parameters_message_type
        )

        metadata_response = v3_measurement_service_pb2.GetMetadataResponse(
            measurement_details=measurement_details,
            measurement_signature=measurement_signature,
            user_interface_details=None,
        )

        for ui_file_path in self._measurement_info.ui_file_paths:
            ui_details = v3_measurement_service_pb2.UserInterfaceDetails(
                file_url=pathlib.Path(ui_file_path).as_uri()
            )
            metadata_response.user_interface_details.append(ui_details)

        return metadata_response

    async def Measure(  # noqa: N802 - function name should be lowercase
        self,
        request: AsyncIterable[v3_measurement_service_pb2.MeasureRequest],
        context: grpc.aio.ServicerContext,
    ) -> AsyncGenerator[v3_measurement_service_pb2.MeasureResponse, None]:
        """RPC API that executes the registered measurement method."""
        self._validate_parameters(request)
        mapping_by_id = decoder.deserialize_parameters(
            self._configuration_metadata,
            request.configuration_parameters.value,
            self._configuration_parameters_message_type,
        )
        mapping_by_variable_name = _get_mapping_by_parameter_name(
            mapping_by_id, self._measure_function
        )
        pin_map_context = PinMapContext._from_grpc(request.pin_map_context)
        token = measurement_service_context.set(
            MeasurementServiceContext(context, pin_map_context, self._owner)
        )
        try:
            async for response in self._measure_function(**mapping_by_variable_name):
                yield response
        finally:
            measurement_service_context.get().mark_complete()
            measurement_service_context.reset(token)

    def _validate_parameters(self, request: v3_measurement_service_pb2.MeasureRequest) -> None:
        expected_type = "type.googleapis.com/" + self._configuration_parameters_message_type
        actual_type = request.configuration_parameters.type_url
        if actual_type != expected_type:
            warnings.warn(
                f"Wrong message type. Expected {expected_type!r} but got {actual_type!r}",
                WrongMessageTypeWarning,
            )
