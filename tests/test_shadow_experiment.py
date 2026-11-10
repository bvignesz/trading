from copy import deepcopy
from dataclasses import replace
import unittest

from trading_engine.shadow_experiment import (
    ExperimentManifest,
    ExperimentValidationError,
    run_shadow_experiment,
)


def make_snapshot():
    return {
        "signal_id": "20261110-LT-BREAKOUT",
        "pipeline": "BREAKOUT",
        "as_of_date": "2026-11-10",
        "participation_state": "PARTICIPATION_CONFIRMED",
        "safety_status": "PASS",
        "liquidity_status": "PASS",
        "trigger": 3920.0,
        "structural_stop": 3848.0,
        "next_resistance": 4075.0,
        "minimum_net_rr": 1.5,
    }


def make_manifest():
    return ExperimentManifest(
        experiment_id="EXP-20261110-PARTICIPATION-RANK",
        pipeline="BREAKOUT",
        hypothesis="Participation may improve ordering among valid setups",
        changed_field="participation_ranking_points",
        champion_value=0,
        challenger_value=1,
        start_date="2026-11-10",
    )


def champion_router(evidence):
    protected = (
        "safety_status", "liquidity_status", "trigger",
        "structural_stop", "next_resistance", "minimum_net_rr",
    )
    return {
        "decision": "WATCH",
        "ranking_score": 6,
        **{key: evidence[key] for key in protected},
    }


def challenger_router(evidence, manifest):
    result = dict(champion_router(evidence))
    if evidence["participation_state"] == "PARTICIPATION_CONFIRMED":
        result["ranking_score"] += manifest.challenger_value
    return result


class ShadowExperimentTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = make_snapshot()
        self.manifest = make_manifest()

    def test_rank_changes_but_live_decision_and_snapshot_do_not(self):
        original = deepcopy(self.snapshot)
        result = run_shadow_experiment(
            evidence_snapshot=self.snapshot,
            manifest=self.manifest,
            champion_router=champion_router,
            challenger_router=challenger_router,
        )
        self.assertTrue(result["ranking_changed"])
        self.assertEqual(result["executable_decision"], "WATCH")
        self.assertEqual(result["challenger"]["ranking_score"], 7)
        self.assertFalse(result["challenger"]["can_place_order"])
        self.assertEqual(self.snapshot, original)

    def test_protected_field_change_is_rejected(self):
        def bad_challenger(evidence, _manifest):
            result = dict(champion_router(evidence))
            result["structural_stop"] = 3860.0
            return result

        with self.assertRaisesRegex(
            ExperimentValidationError, "protected fields"
        ):
            run_shadow_experiment(
                evidence_snapshot=self.snapshot,
                manifest=self.manifest,
                champion_router=champion_router,
                challenger_router=bad_challenger,
            )

    def test_protected_manifest_field_is_rejected(self):
        invalid = replace(self.manifest, changed_field="minimum_net_rr")
        with self.assertRaisesRegex(
            ExperimentValidationError, "Protected field"
        ):
            invalid.validate()

    def test_reject_cannot_become_ranking_eligible(self):
        def rejecting_champion(_evidence):
            return {"decision": "REJECT", "ranking_score": 0}

        def promoting_challenger(_evidence, _manifest):
            return {
                "decision": "READY", "ranking_score": 99,
                "ranking_eligible": True, "can_place_order": True,
            }

        result = run_shadow_experiment(
            evidence_snapshot=self.snapshot,
            manifest=self.manifest,
            champion_router=rejecting_champion,
            challenger_router=promoting_challenger,
        )
        self.assertEqual(result["executable_decision"], "REJECT")
        self.assertFalse(result["challenger"]["ranking_eligible"])
        self.assertFalse(result["challenger"]["can_place_order"])

    def test_pre_start_snapshot_is_not_forward_evidence(self):
        self.snapshot["as_of_date"] = "2026-11-09"
        with self.assertRaisesRegex(ExperimentValidationError, "predates"):
            run_shadow_experiment(
                evidence_snapshot=self.snapshot,
                manifest=self.manifest,
                champion_router=champion_router,
                challenger_router=challenger_router,
            )

    def test_minimum_sample_cannot_be_reduced(self):
        invalid = replace(self.manifest, minimum_matured=29)
        with self.assertRaisesRegex(
            ExperimentValidationError, "at least 30"
        ):
            invalid.validate()


if __name__ == "__main__":
    unittest.main()
