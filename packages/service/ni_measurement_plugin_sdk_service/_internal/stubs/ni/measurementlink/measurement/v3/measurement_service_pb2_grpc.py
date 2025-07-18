# Generated by the gRPC Python protocol compiler plugin. DO NOT EDIT!
"""Client and server classes corresponding to protobuf-defined services."""
import grpc

from ni_measurement_plugin_sdk_service._internal.stubs.ni.measurementlink.measurement.v3 import measurement_service_pb2 as ni_dot_measurementlink_dot_measurement_dot_v3_dot_measurement__service__pb2


class MeasurementServiceStub(object):
    """Service that implements a measurement. Unlike other services, a MeasurementService is designed to be a plugin
    where there can be multiple implementations of the service that provide different measurement capabilities.
    """

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.GetMetadata = channel.unary_unary(
                '/ni.measurementlink.measurement.v3.MeasurementService/GetMetadata',
                request_serializer=ni_dot_measurementlink_dot_measurement_dot_v3_dot_measurement__service__pb2.GetMetadataRequest.SerializeToString,
                response_deserializer=ni_dot_measurementlink_dot_measurement_dot_v3_dot_measurement__service__pb2.GetMetadataResponse.FromString,
                )
        self.Measure = channel.stream_stream(
                '/ni.measurementlink.measurement.v3.MeasurementService/Measure',
                request_serializer=ni_dot_measurementlink_dot_measurement_dot_v3_dot_measurement__service__pb2.MeasureRequest.SerializeToString,
                response_deserializer=ni_dot_measurementlink_dot_measurement_dot_v3_dot_measurement__service__pb2.MeasureResponse.FromString,
                )


class MeasurementServiceServicer(object):
    """Service that implements a measurement. Unlike other services, a MeasurementService is designed to be a plugin
    where there can be multiple implementations of the service that provide different measurement capabilities.
    """

    def GetMetadata(self, request, context):
        """Returns information that describes the measurement.
        """
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def Measure(self, request_iterator, context):
        """API used to perform a measurement.
        """
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')


def add_MeasurementServiceServicer_to_server(servicer, server):
    rpc_method_handlers = {
            'GetMetadata': grpc.unary_unary_rpc_method_handler(
                    servicer.GetMetadata,
                    request_deserializer=ni_dot_measurementlink_dot_measurement_dot_v3_dot_measurement__service__pb2.GetMetadataRequest.FromString,
                    response_serializer=ni_dot_measurementlink_dot_measurement_dot_v3_dot_measurement__service__pb2.GetMetadataResponse.SerializeToString,
            ),
            'Measure': grpc.stream_stream_rpc_method_handler(
                    servicer.Measure,
                    request_deserializer=ni_dot_measurementlink_dot_measurement_dot_v3_dot_measurement__service__pb2.MeasureRequest.FromString,
                    response_serializer=ni_dot_measurementlink_dot_measurement_dot_v3_dot_measurement__service__pb2.MeasureResponse.SerializeToString,
            ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
            'ni.measurementlink.measurement.v3.MeasurementService', rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))


 # This class is part of an EXPERIMENTAL API.
class MeasurementService(object):
    """Service that implements a measurement. Unlike other services, a MeasurementService is designed to be a plugin
    where there can be multiple implementations of the service that provide different measurement capabilities.
    """

    @staticmethod
    def GetMetadata(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(request, target, '/ni.measurementlink.measurement.v3.MeasurementService/GetMetadata',
            ni_dot_measurementlink_dot_measurement_dot_v3_dot_measurement__service__pb2.GetMetadataRequest.SerializeToString,
            ni_dot_measurementlink_dot_measurement_dot_v3_dot_measurement__service__pb2.GetMetadataResponse.FromString,
            options, channel_credentials,
            insecure, call_credentials, compression, wait_for_ready, timeout, metadata)

    @staticmethod
    def Measure(request_iterator,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.stream_stream(request_iterator, target, '/ni.measurementlink.measurement.v3.MeasurementService/Measure',
            ni_dot_measurementlink_dot_measurement_dot_v3_dot_measurement__service__pb2.MeasureRequest.SerializeToString,
            ni_dot_measurementlink_dot_measurement_dot_v3_dot_measurement__service__pb2.MeasureResponse.FromString,
            options, channel_credentials,
            insecure, call_credentials, compression, wait_for_ready, timeout, metadata)
