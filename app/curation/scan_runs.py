from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import exists, or_
from sqlalchemy.orm import Query, Session

from app.models import (
    CurationScanRun,
    CurationScanRunCandidate,
    ProductCandidate,
)


def start_scan_run(
    db: Session,
    *,
    scan_run_id: str,
    source_url: str,
    merchant_name: str,
    target_city_slug: str,
    normalized_category: str | None,
    requested_image_mode: str,
    requested_limit: int,
) -> CurationScanRun:
    run = CurationScanRun(
        id=scan_run_id,
        status="running",
        source_url=source_url,
        source_host=(urlparse(source_url).hostname or "").lower() or None,
        merchant_name=merchant_name,
        target_city_slug=target_city_slug,
        normalized_category=normalized_category,
        requested_image_mode=requested_image_mode,
        requested_limit=requested_limit,
        warnings=[],
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def update_scan_run_context(
    db: Session,
    run: CurationScanRun,
    *,
    merchant_name: str,
    scanner_name: str,
    source: str,
    source_type: str,
    merchant_verification: str,
    effective_image_mode: str,
) -> None:
    run.merchant_name = merchant_name
    run.scanner_name = scanner_name
    run.source = source
    run.source_type = source_type
    run.merchant_verification = merchant_verification
    run.effective_image_mode = effective_image_mode
    db.commit()


def complete_scan_run(
    db: Session,
    run: CurationScanRun,
    *,
    result: dict[str, Any],
    warnings: list[str],
) -> None:
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    items = result.get("items") if isinstance(result.get("items"), list) else []
    external_ids = {
        str(item.get("external_product_id") or "").strip()
        for item in items
        if isinstance(item, dict) and item.get("external_product_id")
    }

    if run.source and external_ids:
        candidates = (
            db.query(ProductCandidate)
            .filter(ProductCandidate.source == run.source)
            .filter(ProductCandidate.external_product_id.in_(external_ids))
            .all()
        )
        existing_candidate_ids = {
            candidate_id
            for (candidate_id,) in (
                db.query(CurationScanRunCandidate.candidate_id)
                .filter(CurationScanRunCandidate.scan_run_id == run.id)
                .all()
            )
        }
        for candidate in candidates:
            if candidate.id in existing_candidate_ids:
                continue
            db.add(
                CurationScanRunCandidate(
                    scan_run_id=run.id,
                    candidate_id=candidate.id,
                )
            )

    run.status = "completed"
    run.discovered_count = int(summary.get("discovered") or result.get("found") or 0)
    run.selected_count = int(
        summary.get("selected_for_review") or result.get("found") or 0
    )
    run.saved_count = int(
        summary.get("saved")
        or (int(result.get("created") or 0) + int(result.get("updated") or 0))
    )
    run.created_count = int(summary.get("created") or result.get("created") or 0)
    run.updated_count = int(summary.get("updated") or result.get("updated") or 0)
    run.skipped_count = int(
        summary.get("skipped_total") or result.get("skipped_duplicates") or 0
    )
    run.warnings = list(dict.fromkeys(warnings))
    run.summary = summary or None
    run.error_message = None
    run.completed_at = datetime.now(timezone.utc)
    db.commit()


def fail_scan_run(
    db: Session,
    scan_run_id: str,
    *,
    error_message: str,
) -> None:
    db.rollback()
    run = db.query(CurationScanRun).filter(CurationScanRun.id == scan_run_id).first()
    if not run:
        return
    run.status = "failed"
    run.error_message = error_message
    run.completed_at = datetime.now(timezone.utc)
    db.commit()


def apply_scan_run_candidate_filter(
    query: Query,
    scan_run_id: str | None,
) -> Query:
    cleaned_scan_run_id = (scan_run_id or "").strip()
    if not cleaned_scan_run_id:
        return query

    membership_exists = (
        exists()
        .where(CurationScanRunCandidate.scan_run_id == cleaned_scan_run_id)
        .where(CurationScanRunCandidate.candidate_id == ProductCandidate.id)
    )
    return query.filter(
        or_(
            membership_exists,
            ProductCandidate.scan_run_id == cleaned_scan_run_id,
        )
    )


def scan_run_payload(
    run: CurationScanRun,
    *,
    candidate_count: int = 0,
) -> dict[str, Any]:
    return {
        "id": run.id,
        "status": run.status,
        "source_url": run.source_url,
        "source_host": run.source_host,
        "merchant_name": run.merchant_name,
        "target_city_slug": run.target_city_slug,
        "normalized_category": run.normalized_category,
        "scanner": run.scanner_name,
        "source": run.source,
        "source_type": run.source_type,
        "merchant_verification": run.merchant_verification,
        "requested_image_mode": run.requested_image_mode,
        "effective_image_mode": run.effective_image_mode,
        "requested_limit": run.requested_limit,
        "discovered": run.discovered_count,
        "selected_for_review": run.selected_count,
        "saved": run.saved_count,
        "created": run.created_count,
        "updated": run.updated_count,
        "skipped": run.skipped_count,
        "candidate_count": candidate_count,
        "warnings": run.warnings or [],
        "summary": run.summary,
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }
