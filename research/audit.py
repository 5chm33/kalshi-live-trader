"""Immutable manifest and decision-record primitives for V11 paper research.

No trade or network code belongs here. Records are append-only: modifying a
registered manifest or decision snapshot is rejected rather than overwritten.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def git_commit(root: Path | None = None) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unavailable"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class StrategyManifest:
    strategy_family: str
    strategy_version: str
    hypothesis: str
    market_universe: Mapping[str, Any]
    feature_schema: Mapping[str, str]
    training_start: str
    training_end: str
    holdout_start: str
    holdout_end: str
    first_prospective_at: str
    primary_metric: str
    confidence_interval_method: str
    lower_confidence_bound_threshold: str
    calibration_error_limit: str
    max_variants: int
    execution_lifecycle: str
    created_at: str = field(default_factory=lambda: _utc_now().isoformat())
    code_commit: str = "unavailable"

    def validate(self) -> None:
        if not self.strategy_family or not self.strategy_version or not self.hypothesis:
            raise ValueError("strategy family, version, and hypothesis are required")
        if self.max_variants < 1:
            raise ValueError("max_variants must be at least one")
        train_end = datetime.fromisoformat(self.training_end.replace("Z", "+00:00"))
        holdout_start = datetime.fromisoformat(self.holdout_start.replace("Z", "+00:00"))
        holdout_end = datetime.fromisoformat(self.holdout_end.replace("Z", "+00:00"))
        first_prospective = datetime.fromisoformat(self.first_prospective_at.replace("Z", "+00:00"))
        if train_end >= holdout_start:
            raise ValueError("training must end before holdout starts")
        if holdout_start > holdout_end:
            raise ValueError("holdout start must not exceed holdout end")
        if first_prospective < train_end:
            raise ValueError("first prospective observation cannot precede training end")
        if self.execution_lifecycle not in {"entry_to_settlement", "entry_to_exit", "structural_locked_value"}:
            raise ValueError("unknown execution lifecycle")

    @property
    def payload(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def manifest_id(self) -> str:
        self.validate()
        return sha256(self.payload)


@dataclass(frozen=True)
class DecisionRecord:
    manifest_id: str
    stage: str
    dataset_sha256: str
    available_data_ends_at: str
    decision_timestamp: str
    exclusions: Mapping[str, Any]
    primary_endpoint: str
    promotion_rule: str
    retirement_rule: str
    more_data_rule: str
    falsifier: str
    previous_record_sha256: str | None = None

    @property
    def payload(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def record_sha256(self) -> str:
        return sha256(self.payload)


class AuditSigner:
    """Optional HMAC signer. Key is local-only, never committed to source control."""

    def __init__(self, key: bytes | None = None):
        raw = key or os.environ.get("V11_AUDIT_SIGNING_KEY", "").encode("utf-8")
        self._key = raw

    @classmethod
    def from_file(cls, path: Path, required: bool = False) -> "AuditSigner":
        if not path.exists():
            if required:
                raise ValueError(f"missing local audit signing key: {path}")
            return cls()
        key = path.read_bytes().strip()
        if required and not key:
            raise ValueError(f"empty local audit signing key: {path}")
        return cls(key)

    @property
    def enabled(self) -> bool:
        return bool(self._key)

    def sign(self, digest: str) -> str | None:
        if not self._key:
            return None
        return hmac.new(self._key, digest.encode("ascii"), hashlib.sha256).hexdigest()

    def verify(self, digest: str, signature: str | None) -> bool:
        expected = self.sign(digest)
        return expected is not None and signature is not None and hmac.compare_digest(expected, signature)
