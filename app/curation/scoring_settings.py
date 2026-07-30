from __future__ import annotations

from dataclasses import dataclass
import os

from sqlalchemy.orm import Session

from app.curation.scoring import (
    LEGACY_SCORING_MODE,
    STRICT_DISTINCTIVENESS_SCORING_MODE,
    scoring_profile_payload,
)
from app.models import CurationSetting


CITY_DISTINCTIVENESS_GATE_SETTING = "CITY_DISTINCTIVENESS_GATE_ENABLED"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "enabled"})


def _environment_default_enabled() -> bool:
    return (
        os.getenv(CITY_DISTINCTIVENESS_GATE_SETTING, "")
        .strip()
        .lower()
        in _TRUE_VALUES
    )


def _stored_enabled(value: object, *, fallback: bool) -> bool:
    if isinstance(value, dict):
        stored = value.get("enabled")
        return stored if isinstance(stored, bool) else fallback
    return value if isinstance(value, bool) else fallback


@dataclass(frozen=True)
class CurationScoringConfiguration:
    enabled: bool
    source: str
    updated_by: str | None = None
    updated_at: object | None = None

    @property
    def scoring_mode(self) -> str:
        return (
            STRICT_DISTINCTIVENESS_SCORING_MODE
            if self.enabled
            else LEGACY_SCORING_MODE
        )

    def as_dict(self) -> dict[str, object]:
        payload = scoring_profile_payload(self.scoring_mode)
        payload.update(
            {
                "key": CITY_DISTINCTIVENESS_GATE_SETTING,
                "enabled": self.enabled,
                "source": self.source,
                "updated_by": self.updated_by,
                "updated_at": self.updated_at,
                "historical_scores_change_automatically": False,
            }
        )
        return payload


def get_curation_scoring_configuration(
    db: Session,
) -> CurationScoringConfiguration:
    environment_default = _environment_default_enabled()
    row = (
        db.query(CurationSetting)
        .filter(CurationSetting.key == CITY_DISTINCTIVENESS_GATE_SETTING)
        .first()
    )
    if row is None:
        return CurationScoringConfiguration(
            enabled=environment_default,
            source="environment_default",
        )
    return CurationScoringConfiguration(
        enabled=_stored_enabled(row.value, fallback=environment_default),
        source="database",
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )


def set_curation_scoring_configuration(
    db: Session,
    *,
    enabled: bool,
    updated_by: str,
) -> CurationScoringConfiguration:
    row = (
        db.query(CurationSetting)
        .filter(CurationSetting.key == CITY_DISTINCTIVENESS_GATE_SETTING)
        .first()
    )
    if row is None:
        row = CurationSetting(key=CITY_DISTINCTIVENESS_GATE_SETTING)
        db.add(row)
    row.value = {"enabled": bool(enabled)}
    row.updated_by = updated_by.strip() or "curator-studio"
    db.commit()
    db.refresh(row)
    return CurationScoringConfiguration(
        enabled=bool(enabled),
        source="database",
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )
