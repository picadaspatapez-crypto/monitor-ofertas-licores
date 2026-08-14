from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.matching import build_product_signature
from app.matching.identity import extract_abv_pct, extract_vintage_year
from app.models import DataQualityEvent, Product, ScrapeRun

_BAD_NAMES = {"", "null", "none", "n/a", "na", "producto", "product", "sin nombre", "undefined"}


@dataclass(frozen=True)
class QualityAssessment:
    score: int
    status: str
    issues: tuple[str, ...]
    excluded_from_comparison: bool
    abv_pct: float | None
    vintage_year: int | None
    package_quantity: int



def _valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def assess_product_quality(
    *,
    name: str,
    url: str,
    current_price: int,
    regular_price: int | None,
    discount_pct: float | None,
    previous_price: int | None = None,
) -> QualityAssessment:
    score = 100
    issues: list[str] = []
    critical = False
    normalized_name = re.sub(r"\s+", " ", (name or "").strip()).casefold()

    if normalized_name in _BAD_NAMES:
        score -= 80
        issues.append("invalid_name")
        critical = True
    elif len(normalized_name) < 3:
        score -= 55
        issues.append("name_too_short")
        critical = True

    if not _valid_url(url or ""):
        score -= 35
        issues.append("invalid_url")

    if int(current_price or 0) <= 0:
        score -= 100
        issues.append("non_positive_price")
        critical = True
    elif int(current_price) < 500:
        score -= 35
        issues.append("implausibly_low_price")
    elif int(current_price) > 2_000_000:
        score -= 20
        issues.append("implausibly_high_price")

    if regular_price is not None and int(regular_price) > 0:
        if int(regular_price) < int(current_price):
            score -= 18
            issues.append("regular_below_current")
        else:
            calculated = (int(regular_price) - int(current_price)) / int(regular_price)
            reported = float(discount_pct or 0.0)
            # Collectors historically use both fractions and percentages in fixtures.
            if reported > 1.5:
                reported /= 100.0
            if reported > 0 and abs(calculated - reported) > 0.12:
                score -= 12
                issues.append("discount_mismatch")
            if calculated > 0.90:
                score -= 20
                issues.append("extreme_discount")

    if previous_price and previous_price > 0 and current_price > 0:
        ratio = current_price / previous_price
        if ratio >= 8.0 or ratio <= 0.125:
            score -= 50
            issues.append("extreme_price_jump")
            critical = True
        elif ratio >= 4.0 or ratio <= 0.25:
            score -= 25
            issues.append("large_price_jump")

    signature = build_product_signature(name or "")
    if signature.volume_ml is None:
        score -= 8
        issues.append("unknown_volume")

    abv = extract_abv_pct(name or "")
    vintage = extract_vintage_year(name or "")
    package_quantity = int(signature.pack_count or 1)
    score = max(0, min(100, score))
    excluded = critical or score < 60
    status = "BLOCKED" if excluded else ("WARNING" if score < 80 else "CLEAN")
    return QualityAssessment(
        score=score,
        status=status,
        issues=tuple(dict.fromkeys(issues)),
        excluded_from_comparison=excluded,
        abv_pct=abv,
        vintage_year=vintage,
        package_quantity=package_quantity,
    )


def apply_quality_assessment(
    session: Session,
    *,
    product: Product,
    scrape_run: ScrapeRun | None,
    previous_price: int | None = None,
) -> QualityAssessment:
    assessment = assess_product_quality(
        name=product.name,
        url=product.url,
        current_price=int(product.current_price or 0),
        regular_price=product.regular_price,
        discount_pct=product.discount_pct,
        previous_price=previous_price,
    )
    product.data_quality_score = assessment.score
    product.data_quality_status = assessment.status
    product.data_quality_issues = list(assessment.issues)
    product.excluded_from_comparison = assessment.excluded_from_comparison
    product.abv_pct = assessment.abv_pct
    product.vintage_year = assessment.vintage_year
    product.package_quantity = assessment.package_quantity
    session.add(
        DataQualityEvent(
            product_id=product.id,
            scrape_run_id=(scrape_run.id if scrape_run is not None else None),
            score=assessment.score,
            status=assessment.status,
            issues=list(assessment.issues),
            observed_at=datetime.now(timezone.utc),
        )
    )
    return assessment


@dataclass(frozen=True)
class QualityRunSummary:
    assessed: int
    clean: int
    warnings: int
    blocked: int


def refresh_quality_for_runs(session: Session, run_ids: Iterable[int]) -> QualityRunSummary:
    run_ids = [int(value) for value in run_ids]
    if not run_ids:
        return QualityRunSummary(0, 0, 0, 0)
    products = list(
        session.scalars(
            select(Product)
            .where(Product.last_confirmed_run_id.in_(run_ids))
            .order_by(Product.id)
        )
    )
    counts = {"CLEAN": 0, "WARNING": 0, "BLOCKED": 0}
    for product in products:
        assessment = assess_product_quality(
            name=product.name,
            url=product.url,
            current_price=int(product.current_price or 0),
            regular_price=product.regular_price,
            discount_pct=product.discount_pct,
            previous_price=None,
        )
        product.data_quality_score = assessment.score
        product.data_quality_status = assessment.status
        product.data_quality_issues = list(assessment.issues)
        product.excluded_from_comparison = assessment.excluded_from_comparison
        product.abv_pct = assessment.abv_pct
        product.vintage_year = assessment.vintage_year
        product.package_quantity = assessment.package_quantity
        counts[assessment.status] += 1
    session.flush()
    return QualityRunSummary(len(products), counts["CLEAN"], counts["WARNING"], counts["BLOCKED"])


def pending_quality_count(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count(Product.id)).where(Product.data_quality_status == "WARNING")
        )
        or 0
    )


def summarize_quality_for_runs(session: Session, run_ids: Iterable[int]) -> QualityRunSummary:
    run_ids = [int(value) for value in run_ids]
    if not run_ids:
        return QualityRunSummary(0, 0, 0, 0)
    rows = list(session.execute(
        select(Product.data_quality_status, func.count(Product.id))
        .where(Product.last_confirmed_run_id.in_(run_ids))
        .group_by(Product.data_quality_status)
    ))
    counts = {str(status or "CLEAN"): int(count or 0) for status, count in rows}
    assessed = sum(counts.values())
    return QualityRunSummary(
        assessed=assessed, clean=counts.get("CLEAN", 0),
        warnings=counts.get("WARNING", 0), blocked=counts.get("BLOCKED", 0),
    )
