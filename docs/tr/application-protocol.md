[English](https://github.com/TahsinCr/vehicle-autonomy-core/blob/main/docs/en/application-protocol.md) | **Türkçe**

# MAVLink uygulama protokolü

Bu opsiyonel katman versioned JSON application packet'lerini tek bir MAVLink
payload mesajı üzerinde taşır. Normal telemetriden ayrıdır.

Varsayılanlar: `DEFAULT_APPLICATION_NETWORK=77`,
`DEFAULT_APPLICATION_MESSAGE_TYPE=42000`. Non-finite JSON number ve geçersiz
source/target ID reddedilir.

## Packet

```text
MavlinkApplicationPacket(packet_type, payload={}, packet_id=<generated>,
                         sent_at=<now>, source_system=None,
                         source_component=None, expects_response=False)
```

Payload immutable iç state'e kopyalanır; `to_dict()` yeni dict döndürür.
`sent_at` pozitif/finite olmalı, type ve encoded boyut protocol limitindedir.

## Codec ve assembler

`MavlinkApplicationCodec.encode(packet)` fragment tuple döndürür.
`decode_fragment(payload)` framing'i; `decode_packet(packet_id, body,
source_system=None, source_component=None)` paketi doğrular.

`MavlinkApplicationAssembler(fragment_timeout=10.0,
max_inflight_assemblies=256, max_inflight_bytes=66528,
max_completed_packets=1024)` için `accept(payload, source_system=None,
source_component=None)` paket tamamlanana kadar `None` döndürür. Out-of-order ve
aynı duplicate kabul edilir. Conflict duplicate, CRC, version ve limit hataları
`MavlinkApplicationProtocolError` üretir. `clear()` state'i sıfırlar.

## Channel

`MavlinkApplicationChannel(client, network_id=77, message_type=42000,
target_system=0, target_component=0, local_system=None, local_component=None,
source_systems=None, source_components=None, fragment_timeout=10.0,
max_inflight_assemblies=256, max_inflight_bytes=66528,
max_completed_packets=1024)`.

`start/stop` carrier subscription'ı yönetir. `send(packet_type, payload=None,
packet_id=None, target_system=None, target_component=None,
expects_response=False)` gönderilen packet'i döndürür. Gelenler `packets`,
hatalar `errors` bus'ında yayınlanır.

## Peer ve request/response

`MavlinkApplicationPeer(channel, role, target_system=0, target_component=0,
transport_available=None, heartbeat_payload=None, heartbeat_interval=1.0,
heartbeat_timeout=12.0, stop_timeout=1.0)`.

API: `start`, `stop`, `send`, `request`, `probe`, `refresh_transport`.
`request` parametreleri packet type/payload, `response_types`, `timeout`, target
ID ve `on_sent`; packet ID ile beklenen source'u eşler ve
`MavlinkApplicationResponse(request, response, round_trip_ms)` döndürür. Stop
pending request'leri uyandırır.

`MavlinkApplicationPeerState`: `running`, `transport_available`, `alive`,
`last_seen_at`, `last_liveness_at`, `round_trip_ms`, `packets_in`, `packets_out`,
`last_packet_type`, `last_error`.

## Dispatcher

`MavlinkApplicationDispatcher(peer, workers=1, max_pending=64,
thread_name="MavlinkApplicationDispatch", handlers=None)`.

```python
@dispatcher.register("camera.capture")
def capture(packet):
    return MavlinkApplicationResult.success(
        {"image_id": "42"},
        message="Captured",
    )
```

Handler `MavlinkApplicationResult`, mapping veya `None` döndürür. `workers=1`
sırayı korur; yalnız bağımsız handler'lar için artırılır. `dispatch(packet)`
kabul durumunu döndürür. Stop yeni işi reddeder, pending işi iptal eder ve kapanış
sonrası response engeller. `packet_types` kayıtlı type'ları verir.

`MavlinkApplicationHandlerRegistry`: `register(type, handler, replace=False)`,
`resolve(type)`, `packet_types`. `MavlinkApplicationHandler` callable alias'tır.
`MavlinkApplicationResult(accepted=True, message="", payload={}, response_type="")`
`success` ve `failure` factory'leri sunar. `MavlinkApplicationDispatch(packet,
result)` ikisini eşler.

## Runtime kullanımı

```python
with MavlinkRuntime(endpoint, application_role="station") as link:
    @link.handle("vehicle.status")
    def status(packet):
        return {"received": True}

    link.notify("mission.changed", {"mission_id": 10})
    response = link.request("vehicle.configure", {"rate": 10}, timeout=3.0)
```

`channel_options` ve `peer_options` ilgili constructor'a iletilir. Vehicle ve
component `notify/request/handle` hedefi otomatik scope eder.

## Remote log modelleri

`MavlinkRemoteLogLevel`: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`; UI/YKİ
eşlemesi içermez.

`MavlinkRemoteLogRecord(sequence, source, action, message, level=INFO,
emitted_at=<now>, details={}, device_id=None, correlation_id=None)`;
`to_payload`/`from_payload` sunar.

`MavlinkRemoteLogBatch(session_id, records, created_at=<now>)` aynı dönüşümleri,
`first_sequence` ve `last_sequence` property'lerini sunar.

Sabitler: `REMOTE_LOG_PROTOCOL_VERSION=1`, `REMOTE_LOG_PACKET_TYPE="logs.push"`,
`REMOTE_LOG_MAX_BATCH_RECORDS=16`, `REMOTE_LOG_MAX_BATCH_BYTES=12000`,
`REMOTE_LOG_MAX_DETAILS_BYTES=3000`.
