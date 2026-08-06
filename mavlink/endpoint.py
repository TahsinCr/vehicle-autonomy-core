from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MavlinkEndpoint:
    uri: str = "udp:127.0.0.1:14550"
    baud: int = 115200
    source_system: int = 255
    source_component: int = 0
    dialect: str = "ardupilotmega"
    autoreconnect: bool = True
    heartbeat_timeout: float = 10.0

    def __post_init__(self) -> None:
        normalized_uri = self.normalize_uri(self.uri)
        normalized_dialect = self.dialect.strip()
        object.__setattr__(self, "uri", normalized_uri)
        object.__setattr__(self, "dialect", normalized_dialect)
        if not normalized_uri:
            raise ValueError("MAVLink bağlantı adresi boş olamaz")
        if not normalized_dialect:
            raise ValueError("MAVLink dialect boş olamaz")
        if self.baud <= 0:
            raise ValueError("MAVLink baud değeri pozitif olmalı")
        if not 0 <= self.source_system <= 255:
            raise ValueError("source_system 0..255 aralığında olmalı")
        if not 0 <= self.source_component <= 255:
            raise ValueError("source_component 0..255 aralığında olmalı")
        if self.heartbeat_timeout <= 0:
            raise ValueError("Heartbeat timeout pozitif olmalı")
        self._validate_network_uri(normalized_uri)

    @staticmethod
    def normalize_uri(uri: str) -> str:
        """Treat ``host:port`` as a TCP client address when no scheme is given."""
        normalized = uri.strip()
        if normalized.count(":") != 1:
            return normalized
        host, port = normalized.rsplit(":", 1)
        if (
            host
            and port.isdigit()
            and "/" not in host
            and "\\" not in host
        ):
            return f"tcp:{host}:{port}"
        return normalized

    def connection_kwargs(self) -> dict[str, object]:
        return {
            "baud": self.baud,
            "dialect": self.dialect,
            "autoreconnect": self.autoreconnect,
            "source_system": self.source_system,
            "source_component": self.source_component,
        }

    @classmethod
    def tcp(cls, host: str, port: int, **options: Any) -> "MavlinkEndpoint":
        return cls(uri=cls._network_uri("tcp", host, port), **options)

    @classmethod
    def udp(cls, host: str, port: int, **options: Any) -> "MavlinkEndpoint":
        return cls(uri=cls._network_uri("udp", host, port), **options)

    @classmethod
    def serial(
        cls,
        device: str,
        *,
        baud: int = 115200,
        **options: Any,
    ) -> "MavlinkEndpoint":
        return cls(uri=device.strip(), baud=baud, **options)

    @staticmethod
    def _network_uri(scheme: str, host: str, port: int) -> str:
        normalized_host = host.strip()
        normalized_port = int(port)
        if not normalized_host:
            raise ValueError("MAVLink host boş olamaz")
        if not 1 <= normalized_port <= 65535:
            raise ValueError("MAVLink port 1..65535 aralığında olmalı")
        return f"{scheme}:{normalized_host}:{normalized_port}"

    @staticmethod
    def _validate_network_uri(uri: str) -> None:
        scheme = uri.partition(":")[0].lower()
        if scheme not in {"tcp", "tcpin", "udp", "udpin", "udpout"}:
            return
        try:
            port = int(uri.rsplit(":", 1)[1])
        except (IndexError, ValueError) as exc:
            raise ValueError(f"Geçersiz MAVLink ağ adresi: {uri}") from exc
        if not 1 <= port <= 65535:
            raise ValueError(
                "MAVLink ağ portu 1..65535 aralığında olmalı; baud ayrı bir ayardır"
            )
