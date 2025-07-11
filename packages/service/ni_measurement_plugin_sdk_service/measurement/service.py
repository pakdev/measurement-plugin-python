"""Framework to host measurement service."""

from __future__ import annotations

import json
import sys
import threading
import warnings
from collections.abc import Iterable
from enum import Enum, EnumMeta
from os import path
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, Callable, Literal, Optional, TypeVar, Union

import grpc
from google.protobuf.descriptor import EnumDescriptor

from ni_measurement_plugin_sdk_service import _datatypeinfo
from ni_measurement_plugin_sdk_service._annotations import ENUM_VALUES_KEY, TYPE_SPECIALIZATION_KEY
from ni_measurement_plugin_sdk_service._internal import grpc_servicer
from ni_measurement_plugin_sdk_service._internal.parameter import metadata as parameter_metadata
from ni_measurement_plugin_sdk_service._internal.service_manager import GrpcService
from ni_measurement_plugin_sdk_service.discovery import DiscoveryClient, ServiceLocation
from ni_measurement_plugin_sdk_service.grpc.channelpool import (
    GrpcChannelPool as GrpcChannelPool,
)  # re-export
from ni_measurement_plugin_sdk_service.measurement.info import (
    DataType,
    MeasurementInfo,
    ServiceInfo,
    TypeSpecialization,
)
from ni_measurement_plugin_sdk_service.moniker import MonikerType
from ni_measurement_plugin_sdk_service.session_management import (
    MultiSessionReservation,
    PinMapContext,
    SessionManagementClient,
    SingleSessionReservation,
)

if TYPE_CHECKING:
    from google.protobuf.internal.enum_type_wrapper import _EnumTypeWrapper

    if sys.version_info >= (3, 10):
        from typing import TypeGuard
    else:
        from typing_extensions import TypeGuard

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self

    SupportedEnumType = Union[type[Enum], _EnumTypeWrapper]


class MeasurementContext:
    """Proxy for the Measurement Service's context-local state."""

    @property
    def grpc_context(self) -> grpc.ServicerContext:
        """Get the context for the RPC."""
        return grpc_servicer.measurement_service_context.get().grpc_context

    @property
    def pin_map_context(self) -> PinMapContext:
        """Get the pin map context for the RPC."""
        return grpc_servicer.measurement_service_context.get().pin_map_context

    def add_cancel_callback(self, cancel_callback: Callable[[], None]) -> None:
        """Add a callback which is invoked when the RPC is canceled."""
        grpc_servicer.measurement_service_context.get().add_cancel_callback(cancel_callback)

    def cancel(self) -> None:
        """Cancel the RPC."""
        grpc_servicer.measurement_service_context.get().cancel()

    @property
    def time_remaining(self) -> float:
        """Get the time remaining for the RPC."""
        return grpc_servicer.measurement_service_context.get().time_remaining

    def abort(self, code: grpc.StatusCode, details: str) -> None:
        """Aborts the RPC."""
        grpc_servicer.measurement_service_context.get().abort(code, details)

    @property
    def _measurement_service(self) -> MeasurementService:
        owner = grpc_servicer.measurement_service_context.get().owner
        assert isinstance(owner, MeasurementService)
        return owner

    def reserve_session(
        self,
        pin_or_relay_names: str | Iterable[str],
        timeout: float | None = 0.0,
    ) -> SingleSessionReservation:
        """Reserve a single session.

        Reserve the session matching the given pins, sites, and instrument type ID and return
        the information needed to create or access the session.

        Args:
            pin_or_relay_names: One or multiple pins, pin groups, relays, or relay groups to
                use for the measurement.

            timeout: Timeout in seconds.

                Allowed values: 0 (non-blocking, fails immediately if resources cannot be
                reserved), -1 (infinite timeout), or any other positive numeric value (wait for
                that number of seconds)

        Returns:
            A reservation object with which you can query information about the session and
            unreserve it.
        """
        if not pin_or_relay_names:
            raise ValueError("You must specify at least one pin or relay name.")
        return self._measurement_service.session_management_client.reserve_session(
            context=self.pin_map_context, pin_or_relay_names=pin_or_relay_names, timeout=timeout
        )

    def reserve_sessions(
        self,
        pin_or_relay_names: str | Iterable[str],
        timeout: float | None = 0.0,
    ) -> MultiSessionReservation:
        """Reserve multiple sessions.

        Reserve sessions matching the given pins, sites, and instrument type ID and return the
        information needed to create or access the sessions.

        Args:
            pin_or_relay_names: One or multiple pins, pin groups, relays, or relay groups to use
                for the measurement.

            timeout: Timeout in seconds.

                Allowed values: 0 (non-blocking, fails immediately if resources cannot be
                reserved), -1 (infinite timeout), or any other positive numeric value (wait for
                that number of seconds)

        Returns:
            A reservation object with which you can query information about the sessions and
            unreserve them.
        """
        if not pin_or_relay_names:
            raise ValueError("You must specify at least one pin or relay name.")
        return self._measurement_service.session_management_client.reserve_sessions(
            context=self.pin_map_context, pin_or_relay_names=pin_or_relay_names, timeout=timeout
        )


_F = TypeVar("_F", bound=Callable)


class MeasurementService:
    """Class that supports registering and hosting a python function as a gRPC service."""

    def __init__(
        self,
        service_config_path: Path,
        version: str = "",
        ui_file_paths: list[Path] = [],
        service_class: str | None = None,
    ) -> None:
        """Initialize the Measurement Service object.

        Uses the specified .serviceconfig file, version, and UI file paths
        to initialize a Measurement Service object.

        Args:
            service_config_path (Path): Path to the .serviceconfig file.

            version (str): Version of the measurement service. Do not use this
                parameter.  Instead, specify the "version" field in the
                .serviceconfig file. Default value is "".

            ui_file_paths (List[Path]): List of paths to supported UIs.
                Default value is [].

            service_class (str): The service class from the .serviceconfig to use.
                Default value is None, which will use the first service in the
                .serviceconfig file.

        """
        if not path.exists(service_config_path):
            raise RuntimeError(f"File does not exist. {service_config_path}")

        with open(service_config_path, encoding="utf-8-sig") as service_config_file:
            service_config = json.load(service_config_file)

        if service_class is None:
            service = next(iter(service_config["services"]), None)
        else:
            service = next(
                (s for s in service_config["services"] if s["serviceClass"] == service_class), None
            )
        if not service:
            raise RuntimeError(
                f"Service class '{service_class}' not found in '{service_config_file}'"
            )

        if version:
            warnings.warn(
                "The 'version' constructor parameter is deprecated. Specify the version using the 'version' field in the .serviceconfig file instead.",
                DeprecationWarning,
            )
        config_version = service.get("version")
        if version and config_version is None:
            version = ""
        if config_version is not None:
            if version and version != config_version:
                raise RuntimeError(
                    f"Version mismatch: .serviceconfig version is '{config_version}', but version parameter is '{version}'.",
                )
            version = config_version

        # Note: sphinx-autoapi uses the public attributes' type hints and docstrings.
        self.measurement_info: MeasurementInfo = MeasurementInfo(
            display_name=service["displayName"],
            version=version,
            ui_file_paths=ui_file_paths,
        )
        """Information about the measurement performed by this service."""

        def convert_value_to_str(value: object) -> str:
            if isinstance(value, str):
                return value
            return json.dumps(value, separators=(",", ":"))

        self.service_info: ServiceInfo = ServiceInfo(
            display_name=service["displayName"],
            service_class=service["serviceClass"],
            description_url=service["descriptionUrl"],
            provided_interfaces=service["providedInterfaces"],
            versions=[version],
            annotations={
                key: convert_value_to_str(value)
                for key, value in service.get("annotations", {}).items()
            },
        )
        """Information about this service."""

        self.context: MeasurementContext = MeasurementContext()
        """Accessor for context-local state."""

        self._configuration_parameter_list: list[parameter_metadata.ParameterMetadata] = []
        self._input_parameter_list: dict[str, str] = {}
        self._output_parameter_list: dict[str, str] = {}
        self._measure_function: Callable = self._raise_measurement_method_not_registered

        self._initialization_lock = threading.RLock()
        self._channel_pool: GrpcChannelPool | None = None
        self._discovery_client: DiscoveryClient | None = None
        self._grpc_service: GrpcService | None = None
        self._session_management_client: SessionManagementClient | None = None

    def _raise_measurement_method_not_registered(self) -> Any:
        raise RuntimeError(
            "Measurement method not registered. Use the register_measurement decorator to register it."
        )

    @property
    def channel_pool(self) -> GrpcChannelPool:
        """Pool of gRPC channels used by the service."""
        if self._channel_pool is None:
            with self._initialization_lock:
                if self._channel_pool is None:
                    self._channel_pool = GrpcChannelPool()
        return self._channel_pool

    @property
    def discovery_client(self) -> DiscoveryClient:
        """Client for accessing the NI Discovery Service."""
        if self._discovery_client is None:
            with self._initialization_lock:
                if self._discovery_client is None:
                    self._discovery_client = DiscoveryClient(grpc_channel_pool=self.channel_pool)
        return self._discovery_client

    @property
    def service_location(self) -> ServiceLocation:
        """The location of the service on the network."""
        with self._initialization_lock:
            if self._grpc_service is None:
                raise RuntimeError("Measurement service not running")
            return self._grpc_service.service_location

    @property
    def session_management_client(self) -> SessionManagementClient:
        """Client for accessing the measurement plug-in session management service."""
        if self._session_management_client is None:
            with self._initialization_lock:
                if self._session_management_client is None:
                    self._session_management_client = SessionManagementClient(
                        discovery_client=self.discovery_client,
                        grpc_channel_pool=self.channel_pool,
                    )
        return self._session_management_client

    def register_measurement(self, measurement_function: _F) -> _F:
        """Register a function as the measurement function for a measurement service.

        To declare a measurement function, use this idiom::

            @measurement_service.register_measurement
            @measurement_serivce.input("input1", MonikerType.ScalarData)
            @measurement_service.configuration("Configuration 1", ...)
            @measurement_service.configuration("Configuration 2", ...)
            @measurement_service.output("output1", MonikerType.ScalarData)
            @measurement_service.output("output2", MonikerType.ScalarData)
            def measure(input1, configuration1, configuration2):
                ...
                return (output1, output2)

        See also: :func:`.configuration`, :func:`.output`
        """
        self._measure_function = measurement_function
        return measurement_function

    def configuration(
        self,
        display_name: str,
        type: DataType,
        default_value: Any,
        *,
        instrument_type: str = "",
        enum_type: SupportedEnumType | None = None,
    ) -> Callable[[_F], _F]:
        """Add a configuration parameter to a measurement function.

        This decorator maps the measurement service's configuration parameters
        to Python positional parameters. To add multiple configuration parameters
        to the same measurement function, use this decorator multiple times.
        The order of decorator calls must match the order of positional parameters.

        See also: :func:`.register_measurement`

        Args:
            display_name: Display name of the configuration.

            type: Data type of the configuration.

            default_value: Default value of the configuration.

            instrument_type:
                Filter pins by instrument type. This is only supported when configuration type
                is DataType.IOResource or DataType.Pin (deprecated).

                For NI instruments, use instrument type id constants defined by
                :py:mod:`ni_measurement_plugin_sdk_service.session_management`, such as
                :py:const:`~ni_measurement_plugin_sdk_service.session_management.INSTRUMENT_TYPE_NI_DCPOWER`
                or
                :py:const:`~ni_measurement_plugin_sdk_service.session_management.INSTRUMENT_TYPE_NI_DMM`.

                For custom instruments, use the instrument type id defined in the pin map file.

            enum_type:
                Defines the enum type associated with this configuration parameter. This is only
                supported when configuration type is DataType.Enum or DataType.EnumArray1D.

        Returns:
            Callable that takes in Any Python Function
            and returns the same python function.
        """
        if type == DataType.Pin:
            warnings.warn(
                "DataType.Pin is deprecated. Use DataType.IOResource instead.", DeprecationWarning
            )
        if type == DataType.PinArray1D:
            warnings.warn(
                "DataType.PinArray1D is deprecated. Use DataType.IOResourceArray1D instead.",
                DeprecationWarning,
            )
        if type in [
            DataType.Double2DArray,
            DataType.DoubleXYData,
            DataType.DoubleXYDataArray1D,
            DataType.String2DArray,
        ]:
            raise ValueError(f"{type} is not supported for configuration parameters.")
        data_type_info = _datatypeinfo.get_type_info(type)
        annotations = self._make_annotations_dict(
            data_type_info.type_specialization, instrument_type=instrument_type, enum_type=enum_type
        )
        parameter = parameter_metadata.ParameterMetadata.initialize(
            display_name,
            data_type_info.grpc_field_type,
            data_type_info.repeated,
            default_value,
            annotations,
            data_type_info.message_type,
            enum_type,
        )
        self._configuration_parameter_list.append(parameter)

        def _configuration(func: _F) -> _F:
            return func

        return _configuration

    def input(self, display_name: str, type: MonikerType) -> Callable[[_F], _F]:
        """Add an input parameter to a measurement function.

        This decorator maps the measurement service's input parameters to
        the elements of the tuple passed to the measurement function.
        To add multiple input parameters to the same measurement function,
        use this decorator multiple times.
        The order of decorator calls must match the order of elements
        passed to the measurement function.

        See also: :func:`.register_measurement`

        Args:
            display_name: Display name of the input.

            type: Data type of the input.

        Returns:
            Callable that takes in Any Python Function and
            returns the same python function.
        """
        self._input_parameter_list[display_name] = type.to_url()

        def _input(func: _F) -> _F:
            return func

        return _input

    def output(self, display_name: str, type: MonikerType) -> Callable[[_F], _F]:
        """Add an output parameter to a measurement function.

        This decorator maps the measurement service's output parameters to
        the elements of the tuple returned by the measurement function.
        To add multiple output parameters to the same measurement function,
        use this decorator multiple times.
        The order of decorator calls must match the order of elements
        returned by the measurement function.

        See also: :func:`.register_measurement`

        Args:
            display_name: Display name of the output.

            type: Data type of the output.

        Returns:
            Callable that takes in Any Python Function and
            returns the same python function.
        """
        self._output_parameter_list[display_name] = type.to_url()

        def _output(func: _F) -> _F:
            return func

        return _output

    def listen(self, port: int | None = None):
        """Host the registered measurement method as a gRPC measurement service.

        Raises:
            Exception: If register measurement methods not available.
        """
        with self._initialization_lock:
            if self._measure_function is self._raise_measurement_method_not_registered:
                self._raise_measurement_method_not_registered()
            if self._grpc_service is not None:
                raise RuntimeError("Measurement service already running.")

            self._grpc_service = GrpcService(self.discovery_client, port)
            self._grpc_service.start(
                self.measurement_info,
                self.service_info,
                self._configuration_parameter_list,
                self._input_parameter_list,
                self._output_parameter_list,
                self._measure_function,
                owner=self,
            )

    def _make_annotations_dict(
        self,
        type_specialization: TypeSpecialization,
        *,
        instrument_type: str = "",
        enum_type: SupportedEnumType | None = None,
    ) -> dict[str, str]:
        annotations: dict[str, str] = {}
        if type_specialization == TypeSpecialization.NoType:
            return annotations

        annotations[TYPE_SPECIALIZATION_KEY] = type_specialization.value
        if type_specialization == TypeSpecialization.Pin:
            if instrument_type != "" or instrument_type is not None:
                annotations["ni/pin.instrument_type"] = instrument_type
        if type_specialization == TypeSpecialization.IOResource:
            if instrument_type != "" or instrument_type is not None:
                annotations["ni/ioresource.instrument_type"] = instrument_type
        if type_specialization == TypeSpecialization.Enum:
            if enum_type is not None:
                annotations[ENUM_VALUES_KEY] = self._enum_to_annotations_value(enum_type)
            else:
                raise ValueError("enum_type is required for enum parameters.")

        return annotations

    def _enum_to_annotations_value(self, enum_type: SupportedEnumType) -> str:
        enum_values = {}
        # For protobuf enums, enum_type is an instance of EnumTypeWrapper at run time, so passing
        # it to issubclass() would raise an error.
        if self._is_protobuf_enum(enum_type):
            if 0 not in enum_type.values():
                raise ValueError("The enum does not have a value for 0.")
            for name, value in enum_type.items():
                enum_values[name] = value
        elif isinstance(enum_type, EnumMeta):
            if not any(member.value == 0 for member in enum_type):
                raise ValueError("The enum does not have a value for 0.")
            for member in enum_type:
                enum_values[member.name] = member.value
        return json.dumps(enum_values)

    def _is_protobuf_enum(self, enum_type: SupportedEnumType) -> TypeGuard[_EnumTypeWrapper]:
        # Use EnumDescriptor to check for protobuf enums at run time without using
        # google.protobuf.internal.
        return isinstance(getattr(enum_type, "DESCRIPTOR", None), EnumDescriptor)

    def close_service(self) -> None:
        """Stop the gRPC measurement service.

        This method stops the gRPC server, unregisters with the discovery service, and cleans up
        the cached discovery client and gRPC channel pool.

        After calling close_service(), you may call host_service() again.

        Exiting the measurement service's runtime context automatically calls close_service().
        """
        with self._initialization_lock:
            if self._grpc_service is not None:
                self._grpc_service.stop()
            if self._channel_pool is not None:
                self._channel_pool.close()

            self._grpc_service = None
            self._channel_pool = None
            self._discovery_client = None

    def __enter__(self: Self) -> Self:
        """Enter the runtime context related to the measurement service."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        """Exit the runtime context related to the measurement service."""
        self.close_service()
        return False

    def get_channel(self, provided_interface: str, service_class: str = "") -> grpc.Channel:
        """Return gRPC channel to specified service.

        Args:
            provided_interface (str): The gRPC Full Name of the service.

            service_class (str): The service "class" that should be matched.

        Returns:
            grpc.Channel: A channel to the gRPC service.

        Raises:
            Exception: If service_class is not specified and there is more than one matching service
                registered.
        """
        service_location = self.discovery_client.resolve_service(provided_interface, service_class)
        channel = self.channel_pool.get_channel(service_location.insecure_address)
        return channel
