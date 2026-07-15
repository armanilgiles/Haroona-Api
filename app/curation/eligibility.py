from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


ELIGIBLE = "eligible"
NEEDS_REVIEW = "needs_review"
INELIGIBLE = "ineligible"
WARNING_REASONS = frozenset({"missing_price", "missing_currency"})


@dataclass(frozen=True)
class EligibilityResult:
    status: str
    blocking_reasons: list[str]
    warning_reasons: list[str]

    @property
    def is_eligible(self) -> bool:
        return self.status != INELIGIBLE

    @property
    def reasons(self) -> list[str]:
        return [*self.blocking_reasons, *self.warning_reasons]


def normalize_availability(value: str | None) -> str:
    normalized = (value or "unknown").strip().lower()
    return normalized.replace("-", "_").replace(" ", "_") or "unknown"


def evaluate_candidate_eligibility(
    *,
    title: str | None,
    affiliate_url: str | None,
    merchant_url: str | None,
    image_url: str | None,
    availability: str | None,
    normalized_category: str | None,
    price_amount: Decimal | int | float | str | None,
    currency: str | None,
    require_image: bool = True,
) -> EligibilityResult:
    """Evaluate the non-editorial gates shared by scanners and publishing.

    Price metadata is intentionally a warning rather than a blocker so a
    curator can repair it. Stock, category, URL, title, and the final image are
    hard requirements because those products cannot safely reach discovery.
    """

    blocking: list[str] = []
    warnings: list[str] = []

    if not (title or "").strip():
        blocking.append("missing_title")
    if not ((affiliate_url or "").strip() or (merchant_url or "").strip()):
        blocking.append("missing_product_url")

    availability_status = normalize_availability(availability)
    if availability_status == "out_of_stock":
        blocking.append("out_of_stock")
    elif availability_status != "in_stock":
        blocking.append("availability_unverified")

    if not (normalized_category or "").strip():
        blocking.append("missing_category")
    if require_image and not (image_url or "").strip():
        blocking.append("missing_image")

    if price_amount is None:
        warnings.append("missing_price")
    elif not (currency or "").strip():
        warnings.append("missing_currency")

    status = INELIGIBLE if blocking else NEEDS_REVIEW if warnings else ELIGIBLE
    return EligibilityResult(
        status=status,
        blocking_reasons=blocking,
        warning_reasons=warnings,
    )


def add_reason_counts(counts: dict[str, int], reasons: list[str]) -> None:
    for reason in reasons:
        counts[reason] = counts.get(reason, 0) + 1


def blocking_reasons_only(reasons: list[str]) -> list[str]:
    return [reason for reason in reasons if reason not in WARNING_REASONS]
