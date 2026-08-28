"""Tests du détecteur d'effets de bord L1 (T3)."""

from __future__ import annotations

import datetime as dt

from benchmark_doctor.detectors.l1_sideeffect import detect_side_effects
from benchmark_doctor.models import Category, Severity, Task

TODAY = dt.date(2026, 8, 15)


def task(question: str, site: str | None = None) -> Task:
    return Task(task_id="T--1", question=question, site=site)


def signals(question: str, site: str | None = None) -> set[str]:
    return {f.signal for f in detect_side_effects(task(question, site), today=TODAY)}


def test_une_tache_exigeant_un_compte_est_bloquante():
    findings = detect_side_effects(task("Log in to your account and list your orders", "Amazon"), today=TODAY)
    (f,) = [x for x in findings if x.signal == "auth_required"]
    assert f.category is Category.ACCESS_DENIED
    assert f.severity is Severity.HIGH
    assert f.details["blocking"] is True


def test_un_achat_effectif_est_bloquant():
    assert "purchase_commit" in signals("Find a Blue iPhone and add it to the cart", "Amazon")


def test_check_out_phrastique_n_est_pas_un_achat():
    # « Check out LeBron James' stats » veut dire « consulte », pas « passe à la caisse » :
    # le motif brut produisait 5 faux positifs sur ESPN et Google Map.
    assert "purchase_commit" not in signals("Check out LeBron James' stats on ESPN", "ESPN")
    assert "purchase_commit" in signals("Add the item to the cart and proceed to checkout", "Amazon")


def test_un_motif_nie_ne_declenche_rien():
    # « finish the quiz without login » n'exige justement pas de compte.
    assert "auth_required" not in signals("Finish a grammar quiz without login and tell me your score")
    assert "auth_required" in signals("Log in and finish a grammar quiz")


def test_reserver_exige_un_complement_reservable():
    # Le motif brut `book|reserve` attrape « a fiction book » et « a travel guide book ».
    assert "booking_commit" not in signals("Locate a travel guide book for Japan on Amazon", "Amazon")
    assert "booking_commit" in signals("Book a room with breakfast in Los Angeles", "Booking")


def test_une_ecriture_sur_un_site_tiers_est_bloquante():
    assert "state_mutation" in signals("Star the repository and tell me the new count", "GitHub")


def test_une_action_hors_navigateur_est_bloquante():
    assert "local_action" in signals("Find a route from Chicago to LA, then print the route details")
    # « Print all prime numbers » est une requête de calcul, pas une impression.
    assert "local_action" not in signals("Print all prime numbers between 1000 and 1200", "Wolfram Alpha")


def test_un_message_sortant_est_suspect_sans_etre_bloquant():
    findings = detect_side_effects(task("Send an email to the seller about the item"), today=TODAY)
    (f,) = [x for x in findings if x.signal == "contact_flow"]
    assert f.severity is Severity.MEDIUM
    assert f.severity < Severity.HIGH


def test_une_tache_de_lecture_ne_declenche_rien():
    assert signals("Find a vegetarian lasagna recipe with at least 4.5 stars", "Allrecipes") == set()


def test_les_constats_portent_une_preuve_citee():
    (f,) = [x for x in detect_side_effects(task("Please log in first"), today=TODAY)
            if x.signal == "auth_required"]
    assert f.evidence and "log in" in f.evidence.lower()
    assert f.observed_at == TODAY
