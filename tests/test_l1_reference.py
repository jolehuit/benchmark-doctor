"""Tests du proxy statique de dérive de contenu L1 (T2)."""

from __future__ import annotations

import datetime as dt

from benchmark_doctor.detectors.l1_reference import detect_named_references
from benchmark_doctor.models import Category, Severity, Task

TODAY = dt.date(2026, 8, 15)


def task(question: str, site: str | None = None) -> Task:
    return Task(task_id="T--1", question=question, site=site)


def signals(question: str, site: str | None = None, **kw) -> set[str]:
    return {f.signal for f in detect_named_references(task(question, site), today=TODAY, **kw)}


def test_un_produit_versionne_est_repere():
    findings = detect_named_references(
        task("Find the trade-in value for an iPhone 13 Pro Max", "Apple"), today=TODAY
    )
    (f,) = [x for x in findings if x.signal == "versioned_product"]
    assert f.category is Category.CONTENT_DRIFT
    assert "iPhone 13" in f.details["reference"]


def test_un_palier_d_abonnement_est_repere():
    # Cas d'école de la ground truth : « GitHub Pro does not exist anymore ».
    assert "plan_or_tier" in signals("Compare the features of GitHub Pro and GitHub Team", "GitHub")


def test_une_rubrique_nommee_est_reperee():
    assert "named_ui_section" in signals("Open the 'World News' section on BBC News", "BBC News")


def test_le_proxy_ne_franchit_jamais_le_seuil_du_flag_dur():
    # Il ne peut pas : sans requête réseau, on ne sait pas si la référence existe encore.
    findings = detect_named_references(
        task("Find the M3 Max chip price and the 'Attention Is All You Need' paper"), today=TODAY
    )
    assert findings
    assert all(f.severity < Severity.HIGH for f in findings)
    assert all(f.details["proxy"] is True for f in findings)


def test_le_proxy_indique_la_sonde_de_verification():
    (f,) = [x for x in detect_named_references(task("Buy a MacBook Pro", "Apple"), today=TODAY)
            if x.signal == "versioned_product"]
    assert f.details["verify_with"] == "l2_content"


def test_le_motif_generique_des_chaines_citees_est_desactivable():
    q = "Search ArXiv for papers about 'graph neural networks'"
    assert "named_content" in signals(q, "ArXiv")
    assert "named_content" not in signals(q, "ArXiv", include_named_content=False)


def test_une_tache_sans_reference_nommee_ne_declenche_rien():
    assert signals("Find a hotel in Paris with free WiFi", "Booking") == set()
