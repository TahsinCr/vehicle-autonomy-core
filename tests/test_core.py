from __future__ import annotations

from dataclasses import dataclass
import math
import queue
import threading
import unittest
from abc import ABC

from src.core.abstracts import Model, Service
from src.core.dependency import (
    BaseDependencyContainer,
    CircularDependencyError,
    DependencyContainer,
)
from src.core.events import EventBus
from src.core.mavlink.router import MavlinkMessageRouter
EARTH_RADIUS_M = 6_371_008.8


@dataclass(frozen=True, slots=True)
class Point(Model):
    latitude: float
    longitude: float
    altitude: float = 0.0

    def __post_init__(self) -> None:
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError("Enlem -90..90 aralığında olmalı")
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError("Boylam -180..180 aralığında olmalı")

    def distance_to(self, other: "Point", *, include_altitude: bool = False) -> float:
        lat1, lat2 = math.radians(self.latitude), math.radians(other.latitude)
        delta_lat = lat2 - lat1
        delta_lon = math.radians(other.longitude - self.longitude)
        haversine = (
            math.sin(delta_lat / 2.0) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2.0) ** 2
        )
        ground = 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(haversine)))
        if not include_altitude:
            return ground
        return math.hypot(ground, other.altitude - self.altitude)

    def bearing_to(self, other: "Point") -> float:
        lat1, lat2 = math.radians(self.latitude), math.radians(other.latitude)
        delta_lon = math.radians(other.longitude - self.longitude)
        y = math.sin(delta_lon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
        return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

    def to_list(self) -> list[float]:
        return [self.latitude, self.longitude, self.altitude]

    def to_dict(self) -> dict[str, float]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "altitude": self.altitude,
        }


class _Message:
    def __init__(self, message_type: str, value: int = 0) -> None:
        self._message_type = message_type
        self.value = value

    def get_type(self) -> str:
        return self._message_type


class _AutomaticModel(Model):
    class_value = "not instance state"

    def __init__(self) -> None:
        self.name = "automatic"
        self.values = [1, 2]
        self._private = "hidden"

    @property
    def unsafe_property(self) -> str:
        raise AssertionError("Properties must not be evaluated during serialization")


class _SlottedAutomaticModel(Model):
    __slots__ = ("value", "_private")

    def __init__(self) -> None:
        self.value = 42
        self._private = "hidden"


class _Connection:
    def __init__(self) -> None:
        self.inbox: queue.Queue[_Message] = queue.Queue()
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def receive(self, *, blocking: bool = False, timeout: float | None = None):
        del blocking
        try:
            return self.inbox.get(timeout=timeout)
        except queue.Empty:
            return None

    def evaluate_condition(self, _condition: str) -> bool:
        return True


class CoreTests(unittest.TestCase):
    def test_model_and_service_abstracts_define_the_universal_contracts(self) -> None:
        self.assertTrue(issubclass(Model, ABC))
        self.assertTrue(issubclass(Service, ABC))
        self.assertEqual(Model().to_dict(), {})

    def test_model_serializes_public_dataclass_dict_and_slot_state_automatically(self) -> None:
        regular = _AutomaticModel()
        serialized = regular.to_dict()
        self.assertEqual(serialized, {"name": "automatic", "values": [1, 2]})
        self.assertEqual(_SlottedAutomaticModel().to_dict(), {"value": 42})
        self.assertEqual(Point(1, 2, 3).to_dict(), {
            "latitude": 1,
            "longitude": 2,
            "altitude": 3,
        })

    def test_event_bus_subscription_can_be_cancelled(self) -> None:
        stream = EventBus[int]()
        received: list[int] = []
        subscription = stream.subscribe(received.append)
        stream.publish(1)
        subscription.cancel()
        stream.publish(2)
        self.assertEqual(received, [1])
        self.assertFalse(subscription.active)

    def test_isolated_event_publish_keeps_healthy_subscribers_running(self) -> None:
        stream = EventBus[int]()
        received: list[int] = []
        stream.subscribe(lambda _value: (_ for _ in ()).throw(RuntimeError("broken")))
        stream.subscribe(received.append)
        result = stream.publish(4)
        self.assertEqual(received, [4])
        self.assertEqual(len(result.errors), 1)

    def test_dependency_lifetimes_and_circular_detection(self) -> None:
        root = DependencyContainer()
        root.singleton("singleton", object)
        root.scoped("scoped", object)
        self.assertIs(root.resolve("singleton"), root.resolve("singleton"))

        first_scope = root.create_scope()
        second_scope = root.create_scope()
        self.assertIs(first_scope.resolve("scoped"), first_scope.resolve("scoped"))
        self.assertIsNot(first_scope.resolve("scoped"), second_scope.resolve("scoped"))

        root.transient("a", lambda b: b, dependencies={"b": "b"})
        root.transient("b", lambda a: a, dependencies={"a": "a"})
        with self.assertRaises(CircularDependencyError):
            root.resolve("a")

    def test_application_containers_configure_their_dependency_graph(self) -> None:
        class ValueContainer(BaseDependencyContainer):
            def configure(self) -> None:
                self.singleton(str, factory=lambda: "shared")

        container = ValueContainer(set_as_default=False)
        self.assertEqual(container.resolve(str), "shared")
        self.assertIs(container.resolve(str), container.resolve(str))

    def test_point_distance_and_bearing(self) -> None:
        ankara = Point(39.9334, 32.8597)
        nearby = Point(39.9434, 32.8597)
        self.assertGreater(ankara.distance_to(nearby), 1_000)
        self.assertLess(ankara.distance_to(nearby), 1_200)
        self.assertAlmostEqual(ankara.bearing_to(nearby), 0.0, delta=0.2)

    def test_mavlink_router_is_the_single_reader_and_waits_after_boundary(self) -> None:
        connection = _Connection()
        router = MavlinkMessageRouter(connection)  # type: ignore[arg-type]
        received: list[_Message] = []
        router.messages.subscribe(received.append)
        router.start()
        boundary = router.sequence
        connection.inbox.put(_Message("HEARTBEAT", 7))
        message = router.wait_for("heartbeat", timeout=1.0, after_sequence=boundary)
        router.stop()
        self.assertEqual(message.value, 7)
        self.assertEqual(received, [message])
        self.assertFalse(connection.started)


if __name__ == "__main__":
    unittest.main()
