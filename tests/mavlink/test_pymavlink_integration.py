"""Optional loopback tests that exercise the real pymavlink UDP transport."""

from __future__ import annotations

import socket
import threading
import unittest

from src.core.mavlink.connection import MavlinkConnection
from src.core.mavlink.endpoint import MavlinkEndpoint
from src.core.mavlink.router import MavlinkMessageRouter
from src.core.mavlink.runtime import MavlinkRuntime

try:
    from pymavlink import mavutil
except ImportError:  # pragma: no cover - exercised by the optional CI job
    mavutil = None


@unittest.skipIf(mavutil is None, "pymavlink optional dependency is not installed")
class PymavlinkUdpIntegrationTests(unittest.TestCase):
    def test_runtime_discovers_two_udp_vehicles_on_one_reader(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        runtime = MavlinkRuntime(MavlinkEndpoint(
            f"udpin:127.0.0.1:{port}", heartbeat_timeout=2.0,
        ))
        senders = [mavutil.mavlink_connection(
            f"udpout:127.0.0.1:{port}", source_system=system, source_component=1,
        ) for system in (12, 13)]
        stopped = threading.Event()
        discovered = threading.Event()
        systems = set()

        @runtime.vehicles.on_added
        def added(event):
            systems.add(event.vehicle.system_id)
            if systems == {12, 13}:
                discovered.set()

        def transmit():
            while not stopped.is_set():
                for sender in senders:
                    sender.mav.heartbeat_send(
                        mavutil.mavlink.MAV_TYPE_QUADROTOR,
                        mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA,
                        0, 0, mavutil.mavlink.MAV_STATE_ACTIVE,
                    )
                stopped.wait(0.02)

        thread = threading.Thread(target=transmit, daemon=True)
        thread.start()
        try:
            with runtime:
                self.assertTrue(discovered.wait(2.0))
                for system in (12, 13):
                    vehicle = runtime.vehicles.get(system)
                    self.assertEqual(vehicle.latest("HEARTBEAT").source_system, system)
                    self.assertEqual(len(vehicle.get_components()), 1)
                reader = runtime.router._thread
                self.assertTrue(reader.is_alive())
            self.assertFalse(reader.is_alive())
            self.assertFalse(runtime._registry._monitor.is_alive())
        finally:
            stopped.set()
            thread.join(1)
            runtime.close()
            for sender in senders:
                sender.close()

    def test_connection_and_router_receive_real_udp_heartbeat(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])

        endpoint = MavlinkEndpoint(
            f"udpin:127.0.0.1:{port}",
            heartbeat_timeout=2.0,
        )
        connection = MavlinkConnection(endpoint)
        router = MavlinkMessageRouter(
            connection,
            poll_timeout=0.02,
            stop_timeout=1.0,
        )
        sender = mavutil.mavlink_connection(
            f"udpout:127.0.0.1:{port}",
            source_system=1,
            source_component=1,
        )
        stop_sender = threading.Event()

        def send_heartbeats() -> None:
            while not stop_sender.is_set():
                sender.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_QUADROTOR,
                    mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA,
                    0,
                    0,
                    mavutil.mavlink.MAV_STATE_ACTIVE,
                )
                stop_sender.wait(0.05)

        sender_thread = threading.Thread(target=send_heartbeats, daemon=True)
        sender_thread.start()
        try:
            connection.start()
            router.start()
            boundary = router.sequence
            message = router.wait_for(
                "HEARTBEAT",
                timeout=2.0,
                after_sequence=boundary,
            )
            self.assertEqual(message.get_srcSystem(), 1)
            self.assertEqual(message.get_srcComponent(), 1)
        finally:
            stop_sender.set()
            sender_thread.join(1.0)
            if router.running or connection.is_connected:
                router.stop()
            sender.close()


if __name__ == "__main__":
    unittest.main()
