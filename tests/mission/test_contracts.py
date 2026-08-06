from __future__ import annotations

import unittest

from src.core import Model
from src.core.mission import (
    Mission,
    MissionChain,
    MissionChainSnapshot,
    MissionController,
    MissionEvent,
    MissionEventLevel,
    MissionEventQuery,
    MissionEventType,
    MissionPhase,
    MissionRetryPolicy,
    MissionSnapshot,
    MissionTransitionError,
    ensure_mission_transition,
)


class KamikazeMission(Mission):
    resources = frozenset({"camera", "flight-control"})

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class SurveyMission(Mission):
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class MissionContractTests(unittest.TestCase):
    def test_controller_is_an_abstract_base(self) -> None:
        with self.assertRaises(TypeError):
            MissionController()

    def test_mission_owns_unique_id_default_name_and_optional_custom_name(self) -> None:
        first = KamikazeMission()
        second = KamikazeMission(name="Primary Target")

        self.assertIsInstance(first.id, int)
        self.assertGreater(first.id, 0)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(first.name, "Kamikaze Mission")
        self.assertEqual(second.name, "Primary Target")
        self.assertEqual(first.resources, frozenset({"camera", "flight-control"}))
        self.assertFalse(hasattr(first, "debug"))
        self.assertFalse(hasattr(first, "on_start"))
        with self.assertRaises(ValueError):
            KamikazeMission(name="  ")

    def test_mission_records_implement_model_contract(self) -> None:
        mission = KamikazeMission()
        snapshot = MissionSnapshot(
            mission.id,
            mission.name,
            phase=MissionPhase.RUNNING,
            result={"completed": True},
        )

        self.assertIsInstance(snapshot, Model)
        serialized = snapshot.to_dict()
        self.assertEqual(serialized["mission_id"], mission.id)
        self.assertEqual(serialized["name"], "Kamikaze Mission")
        self.assertEqual(serialized["phase"], MissionPhase.RUNNING)

    def test_retry_policy_validates_attempts_and_delay(self) -> None:
        retry = MissionRetryPolicy(attempts=4, delay=2)
        self.assertEqual((retry.attempts, retry.delay), (4, 2))
        with self.assertRaises(ValueError):
            MissionRetryPolicy(attempts=0)
        with self.assertRaises(ValueError):
            MissionRetryPolicy(attempts=True)
        with self.assertRaises(ValueError):
            MissionRetryPolicy(delay=float("nan"))

    def test_snapshot_detaches_result_and_checkpoints(self) -> None:
        mission = SurveyMission()
        result = {"path": {"points": [1, 2]}}
        checkpoints = {"start": {"position": [3, 4]}}
        snapshot = MissionSnapshot(
            mission.id,
            mission.name,
            phase=MissionPhase.RUNNING,
            progress=0.5,
            result=result,
            checkpoints=checkpoints,
        )
        result["path"]["points"].append(3)  # type: ignore[index,union-attr]
        checkpoints["start"]["position"].append(5)  # type: ignore[index,union-attr]

        self.assertEqual(tuple(snapshot.result["path"]["points"]), (1, 2))
        self.assertEqual(tuple(snapshot.checkpoints["start"]["position"]), (3, 4))
        self.assertEqual(snapshot.evolve(progress=0.75).progress, 0.75)
        with self.assertRaises(ValueError):
            MissionSnapshot(mission.id, mission.name, progress=1.1)

    def test_event_query_filters_cursor_level_mission_and_type(self) -> None:
        event = MissionEvent(
            MissionEventType.LOG,
            "working",
            level=MissionEventLevel.WARNING,
            mission_id=101,
            sequence=8,
        )
        query = MissionEventQuery(
            mission_ids={101},
            event_types={MissionEventType.LOG},
            minimum_level=MissionEventLevel.INFO,
            after_sequence=7,
        )
        self.assertTrue(query.matches(event))
        self.assertFalse(MissionEventQuery(after_sequence=8).matches(event))

    def test_transition_table_accepts_valid_and_rejects_invalid_edges(self) -> None:
        valid = (
            (MissionPhase.REGISTERED, MissionPhase.STARTING),
            (MissionPhase.STARTING, MissionPhase.RUNNING),
            (MissionPhase.RUNNING, MissionPhase.PAUSING),
            (MissionPhase.PAUSING, MissionPhase.PAUSED),
            (MissionPhase.PAUSED, MissionPhase.STOPPING),
            (MissionPhase.STOPPING, MissionPhase.STOPPED),
            (MissionPhase.RUNNING, MissionPhase.SUCCEEDED),
        )
        for previous, current in valid:
            with self.subTest(previous=previous, current=current):
                ensure_mission_transition(previous, current)

        invalid = (
            (MissionPhase.REGISTERED, MissionPhase.SUCCEEDED),
            (MissionPhase.RUNNING, MissionPhase.REGISTERED),
            (MissionPhase.SUCCEEDED, MissionPhase.PAUSED),
        )
        for previous, current in invalid:
            with self.subTest(previous=previous, current=current):
                with self.assertRaises(MissionTransitionError):
                    ensure_mission_transition(previous, current)

    def test_mission_chain_accepts_repeated_types_and_rejects_invalid_entries(self) -> None:
        chain = MissionChain("survey.chain", (KamikazeMission, SurveyMission))
        self.assertEqual(chain.mission_types, (KamikazeMission, SurveyMission))
        self.assertIs(
            MissionChainSnapshot(chain, active=True).current_mission_type,
            KamikazeMission,
        )
        with self.assertRaises(ValueError):
            MissionChain("survey.chain", ())
        repeated = MissionChain(
            "repeated.chain",
            (KamikazeMission, KamikazeMission),
        )
        self.assertEqual(len(repeated.mission_types), 2)
        with self.assertRaises(ValueError):
            MissionChain("survey.chain", (str,))  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            MissionChainSnapshot(chain, current_index=-1, active=True)


if __name__ == "__main__":
    unittest.main()
