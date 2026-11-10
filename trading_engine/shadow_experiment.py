"""Prospective champion/challenger experiments with no trading authority.

This module deliberately does not calculate strategy evidence.  It receives a
frozen snapshot created by the production engine and compares the production
router (champion) with a one-rule challenger.  Only the champion decision can
remain executable.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from typing import Any, Callable, Mapping


PROTECTED_FIELDS = frozenset(
    {
        "safety_status",
        "liquidity_status",
        "trigger",
        "structural_stop",
        "next_resistance",
        "minimum_net_rr",
        "maximum_positions",
        "maximum_sector_positions",
        "maximum_total_risk_pct",
    }
)

NON_EXECUTABLE_DECISIONS = frozenset({"REJECT", "PENDING_EVIDENCE"})


class ExperimentValidationError(ValueError):
    """Raised when an experiment violates the shadow-research contract."""


@dataclass(frozen=True, slots=True)
class ExperimentManifest:
    experiment_id: str
    pipeline: str
    hypothesis: str
    changed_field: str
    champion_value: Any
    challenger_value: Any
    start_date: str
    minimum_matured: int = 30
    authority: str = "SHADOW_ONLY"
    can_place_order: bool = False
    manifest_version: str = "SHADOW-EXPERIMENT-1.0"

    def validate(self) -> None:
        if not self.experiment_id.strip():
            raise ExperimentValidationError("experiment_id is required")
        if not self.pipeline.strip():
            raise ExperimentValidationError("pipeline is required")
        if not self.hypothesis.strip():
            raise ExperimentValidationError("hypothesis is required")
        if self.changed_field in PROTECTED_FIELDS:
            raise ExperimentValidationError(
                f"Protected field cannot be shadow-tuned: {self.changed_field}"
            )
        if self.champion_value == self.challenger_value:
            raise ExperimentValidationError(
                "Champion and challenger values must differ"
            )
        if self.minimum_matured < 30:
            raise ExperimentValidationError(
                "Experiment requires at least 30 matured observations"
            )
        if self.authority != "SHADOW_ONLY" or self.can_place_order:
            raise ExperimentValidationError(
                "Challenger must remain shadow-only and non-executable"
            )
        try:
            date.fromisoformat(self.start_date)
        except ValueError as exc:
            raise ExperimentValidationError(
                "start_date must use ISO YYYY-MM-DD format"
            ) from exc


def snapshot_hash(evidence: Mapping[str, Any]) -> str:
    payload = json.dumps(
        evidence,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require_snapshot_fields(evidence: Mapping[str, Any]) -> None:
    missing = [key for key in ("signal_id", "pipeline", "as_of_date") if not evidence.get(key)]
    if missing:
        raise ExperimentValidationError(
            f"Frozen evidence is missing required fields: {missing}"
        )


def _assert_protected_outputs_unchanged(
    champion: Mapping[str, Any], challenger: Mapping[str, Any]
) -> None:
    changed = [
        field
        for field in PROTECTED_FIELDS
        if field in champion
        and field in challenger
        and champion[field] != challenger[field]
    ]
    if changed:
        raise ExperimentValidationError(
            f"Challenger altered protected fields: {sorted(changed)}"
        )


def run_shadow_experiment(
    *,
    evidence_snapshot: Mapping[str, Any],
    manifest: ExperimentManifest,
    champion_router: Callable[[dict[str, Any]], Mapping[str, Any]],
    challenger_router: Callable[
        [dict[str, Any], ExperimentManifest], Mapping[str, Any]
    ],
) -> dict[str, Any]:
    """Run one prospective shadow comparison against identical evidence.

    Deep copies isolate both routers.  Hash checks additionally detect mutation
    of the caller-owned snapshot.  A challenger may report a hypothetical
    decision, but the returned executable decision always comes from champion.
    """

    manifest.validate()
    _require_snapshot_fields(evidence_snapshot)

    if evidence_snapshot["pipeline"] != manifest.pipeline:
        raise ExperimentValidationError("Experiment pipeline mismatch")
    if str(evidence_snapshot["as_of_date"]) < manifest.start_date:
        raise ExperimentValidationError(
            "Snapshot predates prospective experiment start_date"
        )

    original_hash = snapshot_hash(evidence_snapshot)
    champion = dict(champion_router(deepcopy(dict(evidence_snapshot))))
    challenger = dict(
        challenger_router(deepcopy(dict(evidence_snapshot)), manifest)
    )

    if snapshot_hash(evidence_snapshot) != original_hash:
        raise RuntimeError("Router modified the caller-owned evidence snapshot")

    _assert_protected_outputs_unchanged(champion, challenger)

    # Missing evidence and confirmed hard failures cannot become eligible even
    # hypothetically.  All challenger results remain non-executable regardless.
    if champion.get("decision") in NON_EXECUTABLE_DECISIONS:
        challenger["ranking_eligible"] = False

    challenger["authority"] = "SHADOW_ONLY"
    challenger["can_place_order"] = False

    return {
        "experiment_id": manifest.experiment_id,
        "pipeline": manifest.pipeline,
        "signal_id": evidence_snapshot["signal_id"],
        "evidence_snapshot_hash": original_hash,
        "champion": champion,
        "challenger": challenger,
        "decision_changed": champion.get("decision")
        != challenger.get("decision"),
        "ranking_changed": champion.get("ranking_score")
        != challenger.get("ranking_score"),
        "changed_field": manifest.changed_field,
        "original_live_decision": champion.get("decision"),
        "executable_decision": champion.get("decision"),
        "challenger_authority": "SHADOW_ONLY",
        "can_change_production": False,
        "module_version": "SHADOW-RUNNER-1.0",
    }
