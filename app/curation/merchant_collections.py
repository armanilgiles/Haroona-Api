from __future__ import annotations

from collections.abc import Iterable, Sequence
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.curation.source_scan_guardrails import normalize_category_hint
from app.models import CurationScanRun, Merchant, MerchantCollection


DEFAULT_COLLECTION_IMPORT_BATCH = "initial_curated_collections_v1"
DEFAULT_COLLECTION_SEED_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / f"{DEFAULT_COLLECTION_IMPORT_BATCH}.json"
)

TRACKING_QUERY_PARAMETERS = {
    "b_fp",
    "fbclid",
    "from_module",
    "from_page",
    "gclid",
    "ipid",
    "referrer_spm",
}


def normalize_merchant_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_merchant_identity(value: str) -> str:
    normalized = normalize_merchant_name(value).casefold().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


def normalize_domain(value: str) -> str:
    candidate = value.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        raise ValueError(f"Invalid merchant domain '{value}'")
    return host


def normalize_collection_url(value: str) -> tuple[str, list[str]]:
    original = value.strip()
    if not original:
        raise ValueError("Collection URL is required")

    issues: list[str] = []
    candidate = original
    if not re.match(r"^[a-z][a-z0-9+.-]*://", candidate, flags=re.IGNORECASE):
        candidate = f"https://{candidate}"
        issues.append("scheme_added")

    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Collection URL must use http or https")
    if parsed.username or parsed.password:
        raise ValueError("Collection URL must not contain credentials")

    host = normalize_domain(parsed.netloc)
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if len(path) > 1:
        path = path.rstrip("/")

    query_items: list[tuple[str, str]] = []
    for key, item_value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered_key = key.lower()
        if lowered_key.startswith("utm_") or lowered_key in TRACKING_QUERY_PARAMETERS:
            if "tracking_parameters_removed" not in issues:
                issues.append("tracking_parameters_removed")
            continue
        query_items.append((key, item_value))
    query_items.sort(key=lambda item: (item[0], item[1]))

    normalized = urlunparse(
        (
            "https",
            host,
            path,
            "",
            urlencode(query_items, doseq=True),
            "",
        )
    )
    return normalized, issues


def stable_merchant_id(*, merchant_name: str, domain: str) -> str:
    material = f"{normalize_merchant_identity(merchant_name)}|{normalize_domain(domain)}"
    return f"merchant_{sha256(material.encode('utf-8')).hexdigest()[:24]}"


def stable_collection_id(normalized_url: str) -> str:
    return f"collection_{sha256(normalized_url.encode('utf-8')).hexdigest()[:24]}"


def infer_collection_category(
    *,
    collection_name: str | None,
    normalized_url: str,
) -> str | None:
    text = unquote(f"{collection_name or ''} {urlparse(normalized_url).path}").lower()
    tokens = set(re.findall(r"[a-z0-9]+", text))

    category_terms: tuple[tuple[str, set[str]], ...] = (
        (
            "outerwear",
            {"outerwear", "coat", "coats", "jacket", "jackets", "puffer", "puffers"},
        ),
        (
            "sweaters_knitwear",
            {
                "sweater",
                "sweaters",
                "knit",
                "knits",
                "knitwear",
                "cardigan",
                "cardigans",
                "pullover",
                "pullovers",
                "sweatshirt",
                "sweatshirts",
                "hoodie",
                "hoodies",
            },
        ),
        (
            "activewear",
            {"active", "activewear", "athleisure", "running", "workout", "sport"},
        ),
        (
            "swimwear",
            {"swim", "swimwear", "swimsuit", "swimsuits", "bikini", "bikinis"},
        ),
        ("dress", {"dress", "dresses", "gown", "gowns", "shirtdress"}),
        (
            "tops",
            {
                "top",
                "tops",
                "shirt",
                "shirts",
                "blouse",
                "blouses",
                "tee",
                "tees",
                "bodysuit",
                "bodysuits",
                "camisole",
                "camisoles",
                "tank",
                "tanks",
                "tunic",
                "tunics",
                "corset",
                "corsets",
                "henley",
                "polo",
                "polos",
            },
        ),
        (
            "bottoms",
            {
                "bottom",
                "bottoms",
                "pant",
                "pants",
                "trouser",
                "trousers",
                "jean",
                "jeans",
                "denim",
                "short",
                "shorts",
                "skirt",
                "skirts",
                "skort",
                "skorts",
                "capri",
                "capris",
            },
        ),
        ("co-ords", {"set", "sets"}),
        ("shoes", {"shoe", "shoes", "footwear"}),
        ("bags", {"bag", "bags", "handbag", "handbags"}),
        ("jewelry", {"jewelry", "jewellery"}),
        ("accessories", {"accessory", "accessories"}),
    )
    for category, terms in category_terms:
        if tokens.intersection(terms):
            return category
    return None


def load_collection_seed(path: Path | str = DEFAULT_COLLECTION_SEED_PATH) -> dict[str, Any]:
    seed_path = Path(path)
    with seed_path.open(encoding="utf-8") as source:
        payload = json.load(source)
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise ValueError(f"Collection seed '{seed_path}' must contain a records list")
    return payload


def import_collection_records(
    db: Session,
    records: Iterable[dict[str, Any]],
    *,
    import_batch: str = DEFAULT_COLLECTION_IMPORT_BATCH,
    include_manual_review: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "import_batch": import_batch,
        "total_input_records": 0,
        "valid_unique_urls": 0,
        "new_merchants_created": 0,
        "existing_merchants_reused": 0,
        "new_collections_created": 0,
        "existing_collections_reused": 0,
        "duplicate_records_skipped": 0,
        "invalid_urls": 0,
        "ambiguous_categories": 0,
        "records_requiring_manual_review": 0,
        "historical_scan_runs_linked": 0,
        "issues": [],
        "dry_run": dry_run,
    }
    seen_urls: set[str] = set()
    created_merchants: set[str] = set()
    reused_merchants: set[str] = set()

    for input_index, raw_record in enumerate(records, start=1):
        report["total_input_records"] += 1
        source_row = raw_record.get("source_row")
        validation_status = str(raw_record.get("validation_status") or "valid")
        if validation_status == "duplicate":
            report["duplicate_records_skipped"] += 1
            continue
        if validation_status == "invalid":
            report["invalid_urls"] += 1
            report["issues"].append(
                {
                    "source_row": source_row,
                    "type": "invalid_url",
                    "message": raw_record.get("notes") or "Seed marked URL invalid",
                }
            )
            continue
        if validation_status == "manual_review" and not include_manual_review:
            report["records_requiring_manual_review"] += 1
            report["issues"].append(
                {
                    "source_row": source_row,
                    "type": "manual_review",
                    "message": raw_record.get("notes") or "Seed requires manual review",
                }
            )
            continue

        merchant_name = normalize_merchant_name(
            str(raw_record.get("merchant_name") or "")
        )
        raw_url = str(
            raw_record.get("collection_url")
            or raw_record.get("original_url")
            or ""
        )
        try:
            normalized_url, normalization_issues = normalize_collection_url(raw_url)
            domain = normalize_domain(str(raw_record.get("domain") or normalized_url))
        except ValueError as exc:
            report["invalid_urls"] += 1
            report["issues"].append(
                {
                    "source_row": source_row,
                    "type": "invalid_url",
                    "message": str(exc),
                }
            )
            continue

        if not merchant_name:
            report["records_requiring_manual_review"] += 1
            report["issues"].append(
                {
                    "source_row": source_row,
                    "type": "missing_merchant",
                    "message": "Merchant name is required",
                }
            )
            continue
        if normalized_url in seen_urls:
            report["duplicate_records_skipped"] += 1
            continue
        seen_urls.add(normalized_url)

        raw_category = raw_record.get("category") or infer_collection_category(
            collection_name=str(raw_record.get("collection_name") or ""),
            normalized_url=normalized_url,
        )
        try:
            category = normalize_category_hint(raw_category)
        except ValueError:
            report["records_requiring_manual_review"] += 1
            report["issues"].append(
                {
                    "source_row": source_row,
                    "type": "unsupported_category",
                    "message": f"Unsupported category '{raw_category}'",
                }
            )
            continue
        if category is None:
            report["ambiguous_categories"] += 1

        normalized_name = normalize_merchant_identity(merchant_name)
        merchant_by_domain = (
            db.query(Merchant)
            .filter(func.lower(Merchant.canonical_domain) == domain)
            .first()
        )
        merchant_by_name = (
            db.query(Merchant)
            .filter(Merchant.normalized_name == normalized_name)
            .first()
        )
        if (
            merchant_by_domain is not None
            and merchant_by_name is not None
            and merchant_by_domain.id != merchant_by_name.id
        ):
            report["records_requiring_manual_review"] += 1
            report["issues"].append(
                {
                    "source_row": source_row,
                    "type": "merchant_identity_conflict",
                    "message": (
                        f"Domain {domain} and merchant name {merchant_name} "
                        "resolve to different merchants"
                    ),
                }
            )
            continue
        if (
            merchant_by_name is not None
            and merchant_by_name.canonical_domain != domain
            and merchant_by_domain is None
        ):
            report["records_requiring_manual_review"] += 1
            report["issues"].append(
                {
                    "source_row": source_row,
                    "type": "merchant_domain_conflict",
                    "message": (
                        f"{merchant_name} already uses "
                        f"{merchant_by_name.canonical_domain}, not {domain}"
                    ),
                }
            )
            continue

        merchant = merchant_by_domain or merchant_by_name
        if merchant is None:
            merchant = Merchant(
                id=str(raw_record.get("merchant_id") or "")
                or stable_merchant_id(merchant_name=merchant_name, domain=domain),
                display_name=merchant_name,
                normalized_name=normalized_name,
                canonical_domain=domain,
                is_active=bool(raw_record.get("is_active", True)),
                import_batch=import_batch,
            )
            db.add(merchant)
            db.flush()
            created_merchants.add(merchant.id)
        elif merchant.id not in created_merchants:
            reused_merchants.add(merchant.id)

        existing_collection = (
            db.query(MerchantCollection)
            .filter(MerchantCollection.normalized_url == normalized_url)
            .first()
        )
        if existing_collection is not None:
            if existing_collection.merchant_id != merchant.id:
                report["records_requiring_manual_review"] += 1
                report["issues"].append(
                    {
                        "source_row": source_row,
                        "type": "collection_merchant_conflict",
                        "message": (
                            f"{normalized_url} already belongs to "
                            f"{existing_collection.merchant_id}"
                        ),
                    }
                )
                continue
            report["existing_collections_reused"] += 1
            if not existing_collection.canonical_category:
                existing_collection.canonical_category = category
            if not existing_collection.notes and raw_record.get("notes"):
                existing_collection.notes = str(raw_record["notes"])
            report["valid_unique_urls"] += 1
            continue

        collection_name = normalize_merchant_name(
            str(raw_record.get("collection_name") or "")
        )
        if not collection_name:
            report["records_requiring_manual_review"] += 1
            report["issues"].append(
                {
                    "source_row": source_row,
                    "type": "missing_collection_name",
                    "message": "Collection name is required",
                }
            )
            continue

        notes = [
            str(raw_record.get("notes") or "").strip(),
            *normalization_issues,
        ]
        collection = MerchantCollection(
            id=str(raw_record.get("collection_id") or "")
            or stable_collection_id(normalized_url),
            merchant_id=merchant.id,
            collection_name=collection_name,
            collection_url=normalized_url,
            normalized_url=normalized_url,
            canonical_category=category,
            city_slug=(
                str(raw_record.get("city") or "").strip().lower().replace("_", "-")
                or None
            ),
            is_active=bool(raw_record.get("is_active", True)),
            import_batch=import_batch,
            notes=", ".join(dict.fromkeys(item for item in notes if item)) or None,
            source_row=int(source_row) if source_row is not None else input_index,
        )
        db.add(collection)
        report["new_collections_created"] += 1
        report["valid_unique_urls"] += 1

    report["new_merchants_created"] = len(created_merchants)
    report["existing_merchants_reused"] = len(reused_merchants)

    collection_ids_by_url = {
        normalized_url: collection_id
        for normalized_url, collection_id in (
            db.query(
                MerchantCollection.normalized_url,
                MerchantCollection.id,
            ).all()
        )
    }
    unlinked_runs = (
        db.query(CurationScanRun)
        .filter(CurationScanRun.collection_id.is_(None))
        .all()
    )
    for run in unlinked_runs:
        try:
            normalized_source_url, _ = normalize_collection_url(run.source_url)
        except ValueError:
            continue
        collection_id = collection_ids_by_url.get(normalized_source_url)
        if collection_id:
            run.collection_id = collection_id
            report["historical_scan_runs_linked"] += 1

    if dry_run:
        db.rollback()
    else:
        db.commit()
    return report


def latest_scan_runs_by_collection(
    db: Session,
    collection_ids: Sequence[str],
) -> dict[str, CurationScanRun]:
    if not collection_ids:
        return {}
    rows = (
        db.query(CurationScanRun)
        .filter(CurationScanRun.collection_id.in_(collection_ids))
        .order_by(
            CurationScanRun.started_at.desc(),
            CurationScanRun.id.desc(),
        )
        .all()
    )
    latest: dict[str, CurationScanRun] = {}
    for row in rows:
        if row.collection_id and row.collection_id not in latest:
            latest[row.collection_id] = row
    return latest


def collection_payload(
    collection: MerchantCollection,
    *,
    merchant: Merchant | None = None,
    latest_run: CurationScanRun | None = None,
) -> dict[str, Any]:
    resolved_merchant = merchant or collection.merchant
    last_product_count = (
        int(latest_run.discovered_count)
        if latest_run is not None
        else None
    )
    last_result: str | None = None
    if latest_run is not None:
        if latest_run.status == "failed":
            last_result = latest_run.error_message or "Scan failed"
        elif latest_run.status == "running":
            last_result = "Scan in progress"
        else:
            summary = latest_run.summary if isinstance(latest_run.summary, dict) else {}
            last_result = str(
                summary.get("message")
                or f"{latest_run.saved_count} candidate(s) saved"
            )
    return {
        "id": collection.id,
        "merchant_id": collection.merchant_id,
        "merchant_name": resolved_merchant.display_name,
        "domain": resolved_merchant.canonical_domain,
        "collection_name": collection.collection_name,
        "collection_url": collection.collection_url,
        "category": collection.canonical_category,
        "city": collection.city_slug,
        "is_active": collection.is_active,
        "import_batch": collection.import_batch,
        "notes": collection.notes,
        "last_scanned_at": (
            latest_run.started_at.isoformat()
            if latest_run is not None and latest_run.started_at
            else None
        ),
        "last_scan_status": latest_run.status if latest_run else "never_scanned",
        "last_scan_result": last_result,
        "last_product_count": last_product_count,
        "has_products": (
            last_product_count > 0 if last_product_count is not None else False
        ),
        "last_scan_run_id": latest_run.id if latest_run else None,
    }
