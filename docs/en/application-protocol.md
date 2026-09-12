**English** | [Türkçe](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/tr/application-protocol.md)

# MAVLink application protocol

This optional layer transports versioned JSON application packets over one
configured MAVLink payload message. It is separate from ordinary telemetry.

Defaults and limits:

- `DEFAULT_APPLICATION_NETWORK = 77`
- `DEFAULT_APPLICATION_MESSAGE_TYPE = 42000`
- packet protocol validation rejects non-finite JSON numbers
- source and target IDs are integers in the MAVLink byte range

## Packet model

```text
MavlinkApplicationPacket(
    packet_type,
    payload={},
    packet_id=<generated>,
    sent_at=<current time>,
    source_system=None,
    source_component=None,
    expects_response=False,
)
```

`payload` is copied into immutable internal state. `to_dict()` returns a new
serializable dictionary. `sent_at` must be positive and finite; packet types and
encoded packet size are bounded by the protocol.

## Codec and assembler

`MavlinkApplicationCodec.encode(packet)` returns one or more byte fragments.
`decode_fragment(payload)` validates fragment framing. `decode_packet(packet_id,
body, source_system=None, source_component=None)` validates and reconstructs a packet.

```python
assembler = MavlinkApplicationAssembler(
    fragment_timeout=10.0,
    max_inflight_assemblies=256,
    max_inflight_bytes=66528,
    max_completed_packets=1024,
)

packet = assembler.accept(
    fragment_payload,
    source_system=12,
    source_component=1,
)
```

`accept()` returns `None` until all fragments arrive and tolerates out-of-order
and identical duplicate fragments. Conflicting duplicates, CRC errors,
unsupported versions and limit violations raise `MavlinkApplicationProtocolError`.
`clear()` discards incomplete/completed deduplication state.

## Channel

```python
MavlinkApplicationChannel(
    client,
    network_id=77,
    message_type=42000,
    target_system=0,
    target_component=0,
    local_system=None,
    local_component=None,
    source_systems=None,
    source_components=None,
    fragment_timeout=10.0,
    max_inflight_assemblies=256,
    max_inflight_bytes=66528,
    max_completed_packets=1024,
)
```

`start()` subscribes to the carrier message; `stop()` detaches it. `send()`
accepts packet type, optional payload, packet ID/targets and
`expects_response`, then returns the sent packet. Incoming decoded packets are
published through `packets`; errors through `errors`.

## Peer and request/response

```python
peer = MavlinkApplicationPeer(
    channel,
    role="vehicle",
    target_system=lambda: 255,
    target_component=lambda: 190,
    transport_available=lambda: client.is_connected,
    heartbeat_payload=None,
    heartbeat_interval=1.0,
    heartbeat_timeout=12.0,
    stop_timeout=1.0,
)
```

Methods:

- `start()` / `stop()`;
- `send(packet_type, payload=None, packet_id=None, target_system=None,
  target_component=None, expects_response=False)`;
- `request(packet_type, payload=None, response_types=..., timeout=...,
  target_system=None, target_component=None, on_sent=None)`;
- `probe()` to send an explicit liveness request;
- `refresh_transport()` after underlying connection state changes.

`request()` correlates packet ID and expected source system/component and returns
`MavlinkApplicationResponse(request, response, round_trip_ms)`. Stop wakes all
pending requests. The monitor does not send or mutate peer state after shutdown.

`MavlinkApplicationPeerState` reports: `running`, `transport_available`, `alive`,
last packet/liveness times, `round_trip_ms`, packet counters, last packet type
and last error.

## Dispatcher

Handlers receive a packet and return `MavlinkApplicationResult`, a mapping, or
`None`.

```python
dispatcher = MavlinkApplicationDispatcher(
    peer,
    workers=1,
    max_pending=64,
    thread_name="MavlinkApplicationDispatch",
)

@dispatcher.register("camera.capture")
def capture(packet):
    return MavlinkApplicationResult.success(
        {"image_id": "42"},
        message="Captured",
    )
```

`workers=1` preserves handler order. Increase it only for independent handlers.
`max_pending` bounds accepted work. `dispatch(packet)` returns whether the packet
was accepted. Stop rejects new work, cancels pending work and prevents responses
after shutdown. `packet_types` on the dispatcher and handler registry returns
the currently registered packet-type names.

`MavlinkApplicationHandlerRegistry` exposes `register(packet_type, handler,
replace=False)` and `resolve(packet_type)`. Registration returns a subscription.

`MavlinkApplicationResult(accepted=True, message="", payload={},
response_type="")` offers `success(payload=None, message="Command accepted")`
and `failure(message, payload=None)`. `MavlinkApplicationDispatch` pairs the
request packet with its result.

## Runtime convenience API

Configure a peer by role directly on the runtime:

```python
with MavlinkRuntime(endpoint, application_role="station") as link:
    @link.handle("vehicle.status")
    def status(packet):
        return {"received": True}

    link.notify("mission.changed", {"mission_id": 10})
    response = link.request(
        "vehicle.configure",
        {"rate": 10},
        timeout=3.0,
    )
```

`channel_options` and `peer_options` forward constructor configuration.
Vehicle/component `notify`, `request` and `handle` automatically scope targets.

## Remote log domain models

`MavlinkRemoteLogLevel` values are `DEBUG`, `INFO`, `WARNING`, `ERROR`, and
`CRITICAL`. It contains no UI/YKİ presentation mapping.

`MavlinkRemoteLogRecord` fields:

- `sequence`, `source`, `action`, `message`;
- `level`, `emitted_at`, `details`;
- optional `device_id`, `correlation_id`.

`to_payload()` and `from_payload()` validate portable transport data.

`MavlinkRemoteLogBatch(session_id, records, created_at=<now>)` groups records and
provides the same conversion methods. `first_sequence` and `last_sequence`
describe the batch range. Limits/constants:

- `REMOTE_LOG_PROTOCOL_VERSION = 1`
- `REMOTE_LOG_PACKET_TYPE = "logs.push"`
- `REMOTE_LOG_MAX_BATCH_RECORDS = 16`
- `REMOTE_LOG_MAX_BATCH_BYTES = 12000`
- `REMOTE_LOG_MAX_DETAILS_BYTES = 3000`
