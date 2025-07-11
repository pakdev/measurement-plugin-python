"""gRPC logging interceptors."""

from __future__ import annotations

import abc
import functools
import logging
import sys
import threading
import time
from collections.abc import Iterator
from types import TracebackType
from typing import TYPE_CHECKING, Any, Callable, Generic, TypeVar

import grpc

if TYPE_CHECKING:
    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self

from ni_measurement_plugin_sdk_service import _tracelogging

_logger = logging.getLogger(__name__)


class ClientLogger(
    grpc.UnaryUnaryClientInterceptor,
    grpc.UnaryStreamClientInterceptor,
    grpc.StreamUnaryClientInterceptor,
    grpc.StreamStreamClientInterceptor,
):
    """Intercepts gRPC client calls and logs them for debugging."""

    @classmethod
    def is_enabled(cls) -> bool:
        """Indicates whether gRPC client call logging is enabled for the current log level."""
        return _ClientCallLogger.is_enabled()

    def intercept_unary_unary(
        self,
        continuation: Callable[
            [grpc.ClientCallDetails, grpc._TRequest], grpc._CallFuture[grpc._TResponse]
        ],
        client_call_details: grpc.ClientCallDetails,
        request: grpc._TRequest,
    ) -> grpc._CallFuture[grpc._TResponse]:
        """Intercept and log a unary call."""
        if _ClientCallLogger.is_enabled():
            call_logger = _ClientCallLogger(client_call_details.method)
            try:
                call = continuation(client_call_details, request)
                return _LoggingResponseCallFuture(call_logger, call)
            except Exception as e:
                call_logger.close(e)
                raise
        else:
            return continuation(client_call_details, request)

    def intercept_unary_stream(
        self,
        continuation: Callable[
            [grpc.ClientCallDetails, grpc._TRequest], grpc._CallIterator[grpc._TResponse]
        ],
        client_call_details: grpc.ClientCallDetails,
        request: grpc._TRequest,
    ) -> grpc._CallIterator[grpc._TResponse]:
        """Intercept and log a server-streaming call."""
        if _ClientCallLogger.is_enabled():
            call_logger = _ClientCallLogger(client_call_details.method)
            try:
                call_iterator = continuation(client_call_details, request)
                return _LoggingResponseCallIterator(call_logger, call_iterator)
            except Exception as e:
                call_logger.close(e)
                raise
        else:
            return continuation(client_call_details, request)

    def intercept_stream_unary(
        self,
        continuation: Callable[
            [grpc.ClientCallDetails, Iterator[grpc._TRequest]], grpc._CallFuture[grpc._TResponse]
        ],
        client_call_details: grpc.ClientCallDetails,
        request_iterator: Iterator[grpc._TRequest],
    ) -> grpc._CallFuture[grpc._TResponse]:
        """Intercept and log a client-streaming call."""
        if _ClientCallLogger.is_enabled():
            call_logger = _ClientCallLogger(client_call_details.method)
            try:
                call = continuation(
                    client_call_details, _LoggingRequestIterator(call_logger, request_iterator)
                )
                return _LoggingResponseCallFuture(call_logger, call)
            except Exception as e:
                call_logger.close(e)
                raise
        else:
            return continuation(client_call_details, request_iterator)

    def intercept_stream_stream(
        self,
        continuation: Callable[
            [grpc.ClientCallDetails, Iterator[grpc._TRequest]], grpc._CallIterator[grpc._TResponse]
        ],
        client_call_details: grpc.ClientCallDetails,
        request_iterator: Iterator[grpc._TRequest],
    ) -> grpc._CallIterator[grpc._TResponse]:
        """Intercept and log a bidirectional streaming call."""
        if _ClientCallLogger.is_enabled():
            call_logger = _ClientCallLogger(client_call_details.method)
            try:
                call_iterator = continuation(
                    client_call_details, _LoggingRequestIterator(call_logger, request_iterator)
                )
                return _LoggingResponseCallIterator(call_logger, call_iterator)
            except Exception as e:
                call_logger.close(e)
                raise
        else:
            return continuation(client_call_details, request_iterator)


class ServerLogger(grpc.ServerInterceptor):
    """Intercepts gRPC server calls and logs them for debugging."""

    @classmethod
    def is_enabled(cls) -> bool:
        """Indicates whether gRPC client call logging is enabled for the current log level."""
        return _ServerCallLogger.is_enabled()

    def intercept_service(
        self,
        continuation: (
            Callable[
                [grpc.HandlerCallDetails],
                grpc.RpcMethodHandler[grpc._TRequest, grpc._TResponse],
            ]
            | None
        ),
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler[grpc._TRequest, grpc._TResponse] | None:
        """Intercept and log a server call."""
        if _ServerCallLogger.is_enabled():
            call_logger = _ServerCallLogger(handler_call_details.method)
            handler = continuation(handler_call_details)
            if handler is None:
                return handler
            elif handler.unary_unary:
                return grpc.unary_unary_rpc_method_handler(
                    functools.partial(self._log_unary_unary, call_logger, handler.unary_unary),
                    handler.request_deserializer,
                    handler.response_serializer,
                )
            elif handler.unary_stream:
                return grpc.unary_stream_rpc_method_handler(
                    functools.partial(self._log_unary_stream, call_logger, handler.unary_stream),
                    handler.request_deserializer,
                    handler.response_serializer,
                )
            elif handler.stream_unary:
                return grpc.stream_unary_rpc_method_handler(
                    functools.partial(self._log_stream_unary, call_logger, handler.stream_unary),
                    handler.request_deserializer,
                    handler.response_serializer,
                )
            elif handler.stream_stream:
                return grpc.stream_stream_rpc_method_handler(
                    functools.partial(self._log_stream_stream, call_logger, handler.stream_stream),
                    handler.request_deserializer,
                    handler.response_serializer,
                )
            else:
                raise RuntimeError("Invalid RpcMethodHandler")
        else:
            return continuation(handler_call_details)

    def _log_unary_unary(
        self,
        call_logger: _CallLogger,
        handler_function: Callable[[grpc._TRequest, grpc.ServicerContext], grpc._TResponse],
        request: grpc._TRequest,
        context: grpc.ServicerContext,
    ) -> grpc._TResponse:
        with call_logger:
            return handler_function(request, context)

    def _log_unary_stream(
        self,
        call_logger: _CallLogger,
        handler_function: Callable[
            [grpc._TRequest, grpc.ServicerContext], Iterator[grpc._TResponse]
        ],
        request: grpc._TRequest,
        context: grpc.ServicerContext,
    ) -> Iterator[grpc._TResponse]:
        try:
            return _LoggingResponseIterator(call_logger, handler_function(request, context))
        except Exception as e:
            call_logger.close(e)
            raise

    def _log_stream_unary(
        self,
        call_logger: _CallLogger,
        handler_function: Callable[
            [Iterator[grpc._TRequest], grpc.ServicerContext], grpc._TResponse
        ],
        request_iterator: Iterator[grpc._TRequest],
        context: grpc.ServicerContext,
    ) -> grpc._TResponse:
        with call_logger:
            return handler_function(_LoggingRequestIterator(call_logger, request_iterator), context)

    def _log_stream_stream(
        self,
        call_logger: _CallLogger,
        handler_function: Callable[
            [Iterator[grpc._TRequest], grpc.ServicerContext], Iterator[grpc._TResponse]
        ],
        request_iterator: Iterator[grpc._TRequest],
        context: grpc.ServicerContext,
    ) -> Iterator[grpc._TResponse]:
        try:
            return _LoggingResponseIterator(
                call_logger,
                handler_function(_LoggingRequestIterator(call_logger, request_iterator), context),
            )
        except Exception as e:
            call_logger.close(e)
            raise


class _CallLogger(abc.ABC):
    """Logs a single call."""

    __slots__ = ["_closed"]

    # As of 2023, the Python stdlib doesn't support atomic operations, so use a global lock to
    # atomically update self._closed.
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._closed = False

    def close(self, exception: BaseException | None = None) -> None:
        # close() is idempotent to avoid duplicate logs.
        with _CallLogger._lock:
            if self._closed:
                return
            self._closed = True

        self._close(exception)

    @abc.abstractmethod
    def _close(self, exception: BaseException | None) -> None:
        raise NotImplementedError()

    def __enter__(self: Self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close(exc_val)

    @abc.abstractmethod
    def log_streaming_request(self) -> None:
        raise NotImplementedError()

    @abc.abstractmethod
    def log_streaming_response(self) -> None:
        raise NotImplementedError()


class _ClientCallLogger(_CallLogger):
    __slots__ = ["_method_name", "_activity_id"]

    @classmethod
    def is_enabled(cls) -> bool:
        return _logger.isEnabledFor(logging.DEBUG) or _tracelogging.is_enabled()

    def __init__(self, method_name: str) -> None:
        super().__init__()
        self._method_name = method_name
        _logger.debug("gRPC client call starting: %s", self._method_name)
        self._activity_id = _tracelogging.log_grpc_client_call_start(self._method_name)

    def _close(self, exception: BaseException | None = None) -> None:
        _logger.debug("gRPC client call complete: %s", self._method_name)
        _tracelogging.log_grpc_client_call_stop(self._method_name, self._activity_id)

    def log_streaming_request(self) -> None:
        _logger.debug("gRPC client call streaming request: %s", self._method_name)
        _tracelogging.log_grpc_client_call_streaming_request(self._method_name)

    def log_streaming_response(self) -> None:
        _logger.debug("gRPC client call streaming response: %s", self._method_name)
        _tracelogging.log_grpc_client_call_streaming_response(self._method_name)


class _ServerCallLogger(_CallLogger):
    __slots__ = ["_method_name", "_start_time", "_activity_id"]

    @classmethod
    def is_enabled(cls) -> bool:
        return _logger.isEnabledFor(logging.INFO) or _tracelogging.is_enabled()

    def __init__(self, method_name: str) -> None:
        super().__init__()
        self._method_name = method_name
        self._start_time = time.perf_counter()
        _logger.debug("gRPC server call starting: %s", self._method_name)
        self._activity_id = _tracelogging.log_grpc_server_call_start(self._method_name)

    def _close(self, exception: BaseException | None = None) -> None:
        if _logger.isEnabledFor(logging.INFO):
            # For production usage, log a concise one-line summary of the call, similar to what
            # Serilog provides for ASP.NET Core services. Don't log exception details because
            # grpcio's logging_pool already handles this.
            elapsed_time = time.perf_counter() - self._start_time
            _logger.info(
                "gRPC server call %s responded %s in %.4f ms",
                self._method_name,
                str(_get_status_code(exception)).replace("StatusCode.", ""),
                elapsed_time * 1000.0,
            )
        _logger.debug("gRPC server call complete: %s", self._method_name)
        _tracelogging.log_grpc_server_call_stop(self._method_name, self._activity_id)

    def log_streaming_request(self) -> None:
        _logger.debug("gRPC server call streaming request: %s", self._method_name)
        _tracelogging.log_grpc_server_call_streaming_request(self._method_name)

    def log_streaming_response(self) -> None:
        _logger.debug("gRPC server call streaming response: %s", self._method_name)
        _tracelogging.log_grpc_server_call_streaming_response(self._method_name)


def _get_status_code(exception: BaseException | None) -> grpc.StatusCode:
    if exception is None:
        return grpc.StatusCode.OK
    elif isinstance(exception, grpc.RpcError):
        return exception.code()
    else:
        return grpc.StatusCode.UNKNOWN


_T = TypeVar("_T")


class _LoggingRequestIterator(Generic[_T]):
    __slots__ = ["_call_logger", "_inner_iterator"]

    def __init__(self, call_logger: _CallLogger, inner_iterator: Iterator[_T]) -> None:
        self._call_logger = call_logger
        self._inner_iterator = inner_iterator

    def __iter__(self) -> Iterator[_T]:
        return self

    def __next__(self) -> _T:
        request = next(self._inner_iterator)
        self._call_logger.log_streaming_request()
        return request


class _LoggingResponseIterator(Generic[_T]):
    __slots__ = ["_call_logger", "_inner_iterator"]

    def __init__(self, call_logger: _CallLogger, inner_iterator: Iterator[_T]) -> None:
        self._call_logger = call_logger
        self._inner_iterator = inner_iterator

    def __iter__(self) -> Iterator[_T]:
        return self

    def __next__(self) -> _T:
        # For server-streaming and bidirectional RPCs, the call is complete when the response
        # stream is closed or it throws an exception.
        try:
            response = next(self._inner_iterator)
            self._call_logger.log_streaming_response()
            return response
        except StopIteration:
            self._call_logger.close()
            raise
        except Exception as e:
            self._call_logger.close(e)
            raise


if TYPE_CHECKING:
    # These types only exist in grpc-stubs.
    _CallFuture = grpc._CallFuture
    _CallIterator = grpc._CallIterator
else:

    class _CallFuture(Generic[_T]):
        pass

    class _CallIterator(Generic[_T]):
        pass


@grpc.Call.register
@grpc.Future.register
class _LoggingResponseCallFuture(_CallFuture[_T]):
    __slots__ = ["_call_logger", "_inner_call_future"]

    def __init__(self, call_logger: _CallLogger, inner_call_future: grpc._CallFuture[_T]) -> None:
        self._call_logger = call_logger
        self._inner_call_future = inner_call_future

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner_call_future, name)

    def result(self, timeout: float | None = None) -> _T:
        # For unary and client-streaming RPCs, the call is complete when it returns a response or
        # throws an exception.
        with self._call_logger:
            return self._inner_call_future.result(timeout)

    def exception(self, timeout: float | None = None) -> Exception | None:
        with self._call_logger:
            return self._inner_call_future.exception(timeout)

    def traceback(self, timeout: float | None = None) -> Any:
        with self._call_logger:
            return self._inner_call_future.traceback(timeout)

    # At run time, __getattr__ forwards these to the inner CallFuture.
    if TYPE_CHECKING:

        def add_callback(self, callback: Callable[[], None]) -> bool: ...
        def add_done_callback(
            self, fn: Callable[[grpc.Future[grpc._TFutureValue]], None]
        ) -> None: ...
        def cancel(self) -> bool: ...
        def cancelled(self) -> bool: ...
        def code(self) -> grpc.StatusCode: ...
        def details(self) -> str: ...
        def done(self) -> bool: ...
        def initial_metadata(self) -> grpc._Metadata: ...
        def is_active(self) -> bool: ...
        def running(self) -> bool: ...
        def time_remaining(self) -> float: ...
        def trailing_metadata(self) -> grpc._Metadata: ...


@grpc.Call.register
@grpc.Future.register
class _LoggingResponseCallIterator(_CallIterator[_T]):
    __slots__ = ["_call_logger", "_inner_call_iterator"]

    def __init__(
        self, call_logger: _CallLogger, inner_call_iterator: grpc._CallIterator[_T]
    ) -> None:
        self._call_logger = call_logger
        self._inner_call_iterator = inner_call_iterator

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner_call_iterator, name)

    def __iter__(self) -> Iterator[_T]:
        return self

    def __next__(self) -> _T:
        # For server-streaming and bidirectional RPCs, the call is complete when the response
        # stream is closed or throws an exception.
        try:
            response = next(self._inner_call_iterator)
            self._call_logger.log_streaming_response()
            return response
        except StopIteration:
            self._call_logger.close()
            raise
        except Exception as e:
            self._call_logger.close(e)
            raise

    # At run time, __getattr__ forwards these to the inner CallIterator.
    if TYPE_CHECKING:

        def add_callback(self, callback: Callable[[], None]) -> bool: ...
        def add_done_callback(
            self, fn: Callable[[grpc.Future[grpc._TFutureValue]], None]
        ) -> None: ...
        def cancel(self) -> bool: ...
        def cancelled(self) -> bool: ...
        def code(self) -> grpc.StatusCode: ...
        def details(self) -> str: ...
        def done(self) -> bool: ...
        def initial_metadata(self) -> grpc._Metadata: ...
        def is_active(self) -> bool: ...
        def running(self) -> bool: ...
        def time_remaining(self) -> float: ...
        def trailing_metadata(self) -> grpc._Metadata: ...
