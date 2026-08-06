"""Reusable MAVLink infrastructure for ArduPilot-based vehicles."""

# ``unittest discover`` imports every package directory below its start path.
# In a source checkout this directory is therefore briefly imported as the
# top-level ``mavlink`` package, even though the supported public package is
# ``<parent>.core.mavlink``. Avoid eager imports only for that discovery probe;
# normal package imports retain the complete public API below.
if __package__ == "mavlink":
    __all__: list[str] = []
else:
    from .cache import MessageCache
    from .channel import MavlinkAsyncChannel
    from .application import (
        DEFAULT_APPLICATION_MESSAGE_TYPE,
        DEFAULT_APPLICATION_NETWORK,
        MavlinkApplicationAssembler,
        MavlinkApplicationChannel,
        MavlinkApplicationCodec,
        MavlinkApplicationPacket,
        MavlinkApplicationProtocolError,
    )
    from .client import MavlinkClient
    from .connection import MavlinkConnection, MavlinkUnavailableError
    from .dispatch import (
        MavlinkApplicationDispatch,
        MavlinkApplicationDispatcher,
        MavlinkApplicationHandler,
        MavlinkApplicationHandlerRegistry,
        MavlinkApplicationResult,
    )
    from .endpoint import MavlinkEndpoint
    from .filter import MavlinkMessageFilter
    from .message import MavlinkMessageEnvelope
    from .protocols import MavlinkHeader, MavlinkMessage
    from .peer import (
        MavlinkApplicationPeer,
        MavlinkApplicationPeerState,
        MavlinkApplicationResponse,
    )
    from .remote_log import (
        MavlinkRemoteLogBatch,
        MavlinkRemoteLogLevel,
        MavlinkRemoteLogRecord,
        REMOTE_LOG_MAX_BATCH_BYTES,
        REMOTE_LOG_MAX_BATCH_RECORDS,
        REMOTE_LOG_MAX_DETAILS_BYTES,
        REMOTE_LOG_PACKET_TYPE,
        REMOTE_LOG_PROTOCOL_VERSION,
    )
    from .router import MavlinkMessageRouter, MavlinkRouterError, MavlinkRouterStats
    from .runtime import MavlinkRuntime, MavlinkRuntimeError, MavlinkRuntimeState

    __all__ = [
        "MavlinkAsyncChannel",
        "MavlinkApplicationAssembler",
        "MavlinkApplicationChannel",
        "MavlinkApplicationCodec",
        "MavlinkApplicationDispatch",
        "MavlinkApplicationDispatcher",
        "MavlinkApplicationHandler",
        "MavlinkApplicationHandlerRegistry",
        "MavlinkApplicationPacket",
        "MavlinkApplicationPeer",
        "MavlinkApplicationPeerState",
        "MavlinkApplicationProtocolError",
        "MavlinkApplicationResponse",
        "MavlinkApplicationResult",
        "MavlinkRemoteLogBatch",
        "MavlinkRemoteLogLevel",
        "MavlinkRemoteLogRecord",
        "DEFAULT_APPLICATION_MESSAGE_TYPE",
        "DEFAULT_APPLICATION_NETWORK",
        "MavlinkClient",
        "MavlinkConnection",
        "MavlinkEndpoint",
        "MavlinkUnavailableError",
        "MavlinkMessageRouter",
        "MavlinkMessageEnvelope",
        "MavlinkMessageFilter",
        "MavlinkHeader",
        "MavlinkMessage",
        "MavlinkRouterError",
        "MavlinkRouterStats",
        "MavlinkRuntime",
        "MavlinkRuntimeError",
        "MavlinkRuntimeState",
        "MessageCache",
        "REMOTE_LOG_MAX_BATCH_BYTES",
        "REMOTE_LOG_MAX_BATCH_RECORDS",
        "REMOTE_LOG_MAX_DETAILS_BYTES",
        "REMOTE_LOG_PACKET_TYPE",
        "REMOTE_LOG_PROTOCOL_VERSION",
    ]
