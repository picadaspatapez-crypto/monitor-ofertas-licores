from __future__ import annotations

import pytest

from app.collectors import cav


def test_cav_page_url_targets_store_not_homepage():
    url = cav._page_url(0, (("fR[family.name][0]", "Vinos"), ("fR[wine_type.name][0]", "Tinto")))
    assert url.startswith("https://cav.cl/tienda?")


def test_cav_effective_catalog_url_accepts_store_with_filters():
    url = cav._page_url(3, (("fR[family.name][0]", "Vinos"), ("fR[wine_type.name][0]", "Tinto")))
    cav._assert_effective_catalog_url(url, url, label="Vinos / Tinto página 4")


def test_cav_effective_catalog_url_rejects_homepage_redirect():
    requested = cav._page_url(0, (("fR[family.name][0]", "Vinos"), ("fR[wine_type.name][0]", "Tinto")))
    with pytest.raises(RuntimeError, match="portada"):
        cav._assert_effective_catalog_url("https://cav.cl/", requested, label="Vinos / Tinto página 1")


def test_cav_rejects_three_identical_small_shard_first_pages():
    signatures = {}
    signature = tuple(f"https://cav.cl/tienda/producto/demo-{i}" for i in range(11))
    cav._register_first_page_signature(signatures, label="Vinos / Tinto", signature=signature)
    cav._register_first_page_signature(signatures, label="Vinos / Blanco", signature=signature)
    with pytest.raises(RuntimeError, match="mismo subconjunto pequeño"):
        cav._register_first_page_signature(signatures, label="Whisky", signature=signature)


def test_cav_does_not_reject_large_identical_signature_guardrail():
    signatures = {}
    signature = tuple(f"https://cav.cl/tienda/producto/demo-{i}" for i in range(cav.STATIC_EDITORIAL_CEILING + 1))
    for label in ("Vinos / Tinto", "Vinos / Blanco", "Whisky"):
        cav._register_first_page_signature(signatures, label=label, signature=signature)
