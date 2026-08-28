"""Tests du détecteur temporel L1.

Le cœur de ces tests est la frontière **transactionnel / archivistique** : c'est la règle
qui fait la valeur du détecteur, et c'est aussi celle qui se casse le plus facilement sur
un cas limite (le mot « book » qui est à la fois un verbe de réservation et un nom commun).
"""

from __future__ import annotations

import datetime as dt

import pytest

from benchmark_doctor.detectors.l1_temporal import (
    TemporalIntent,
    classify_temporal_intent,
    detect_temporal_decay,
    extract_date_mentions,
)
from benchmark_doctor.models import Category, Channel, Severity, Task

TODAY = dt.date(2026, 8, 15)


def task(question: str, site: str | None = None, task_id: str = "T--1") -> Task:
    return Task(task_id=task_id, question=question, site=site)


def signals(findings) -> set[str]:
    return {f.signal for f in findings}


# -- extraction de dates ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected_kind,expected_year",
    [
        ("stay from March 20, 2024", "full", 2024),
        ("submitted on 2024-01-03", "full", 2024),
        ("for 20/12/2023 - 21/12/2023", "full", 2023),
        ("announced in October 2023", "month_year", 2023),
        ("papers published in 2023", "year", 2023),
        ("the 2023-24 season", "season", 2023),
        ("hotel from December 20th", "month_day", None),
        ("leaves on 1st of January", "month_day", None),
    ],
)
def test_extrait_les_formes_de_dates_du_corpus(text, expected_kind, expected_year):
    mentions = extract_date_mentions(text)
    assert mentions, f"aucune date trouvée dans {text!r}"
    assert mentions[0].kind == expected_kind
    assert mentions[0].year == expected_year


def test_une_date_complete_ne_produit_pas_aussi_une_annee_nue():
    mentions = extract_date_mentions("from March 20, 2024 to March 27, 2024")
    assert [m.kind for m in mentions] == ["full", "full"]


def test_ne_confond_pas_les_nombres_du_corpus_avec_des_dates():
    # « 2 adults », « 4.5 stars », « 16-inch » : aucun n'est une date.
    assert extract_date_mentions("a hotel for 2 adults rated 4.5 stars, 16-inch screen") == []


def test_la_pertinence_d_une_date_depend_de_la_date_d_analyse():
    (mention,) = extract_date_mentions("flight on March 20, 2026")
    assert mention.is_past(dt.date(2026, 8, 15))
    assert not mention.is_past(dt.date(2026, 1, 1))
    assert mention.is_future(dt.date(2026, 1, 1))


def test_une_date_sans_millesime_n_est_jamais_declaree_revolue():
    (mention,) = extract_date_mentions("hotel from December 25th")
    assert not mention.is_past(TODAY) and not mention.is_future(TODAY)


# -- classification transactionnel / archivistique -------------------------------------


def test_reserver_un_hotel_est_transactionnel():
    d = classify_temporal_intent(task("Book a hotel in Paris for a stay from March 20-27, 2024", "Booking"))
    assert d.intent is TemporalIntent.TRANSACTIONAL


def test_interroger_un_fonds_documentaire_est_archivistique():
    d = classify_temporal_intent(
        task("On ArXiv, how many articles were originally announced in October 2023?", "ArXiv")
    )
    assert d.intent is TemporalIntent.ARCHIVAL


def test_le_mot_book_comme_nom_ne_rend_pas_la_tache_transactionnelle():
    # Cas limite réel (Amazon--30) : « fiction book released in 2024 ». Le détecteur naïf
    # y voyait le verbe « réserver » et déclarait la tâche morte.
    d = classify_temporal_intent(
        task("Locate the highest-rated fiction book released in 2024 on Amazon", "Amazon")
    )
    assert d.intent is TemporalIntent.ARCHIVAL


def test_une_saison_sportive_passee_reste_archivistique():
    d = classify_temporal_intent(
        task("Who has the heaviest weight among infielders in the Yankees Roster 2023-24?", "ESPN")
    )
    assert d.intent is TemporalIntent.ARCHIVAL


def test_en_cas_de_conflit_lexical_le_site_tranche():
    # « released » (archivistique) et « book a room » (transactionnel) dans le même énoncé :
    # sur Booking.com la sémantique du site l'emporte.
    d = classify_temporal_intent(
        task("Book a room in the hotel released in 2023 in Paris on March 2, 2024", "Booking")
    )
    assert d.intent is TemporalIntent.TRANSACTIONAL
    assert d.rule.startswith("conflict>site")


def test_sans_marqueur_ni_site_connu_l_intention_reste_indeterminee():
    d = classify_temporal_intent(task("Tell me about the 2023 report", "Coursera"))
    assert d.intent is TemporalIntent.UNKNOWN


# -- constats émis ---------------------------------------------------------------------


def test_une_date_passee_sur_tache_transactionnelle_est_un_flag_dur():
    findings = detect_temporal_decay(
        task("Book a hotel in Paris from March 20 to March 27, 2024", "Booking"), today=TODAY
    )
    (f,) = [x for x in findings if x.signal == "past_date_transactional"]
    assert f.category is Category.TEMPORAL
    assert f.severity is Severity.HIGH
    assert f.channel is Channel.STATIC
    assert "2024" in f.evidence
    assert f.details["reference_date"] == "2026-08-15"


def test_une_date_passee_sur_tache_archivistique_n_est_pas_un_flag_dur():
    findings = detect_temporal_decay(
        task("How many papers were announced in October 2023 on ArXiv?", "ArXiv"), today=TODAY
    )
    (f,) = [x for x in findings if x.signal == "past_date_archival"]
    assert f.severity is Severity.LOW
    assert f.severity < Severity.HIGH  # la tâche vieillit, elle ne casse pas


def test_une_date_passee_sur_site_inconnu_reste_moyenne():
    findings = detect_temporal_decay(task("Find the 2023 annual report", "Coursera"), today=TODAY)
    (f,) = [x for x in findings if x.signal == "past_date_unknown"]
    assert f.severity is Severity.MEDIUM


def test_une_date_sans_millesime_releve_de_la_fragilite_d_evaluation():
    # La tâche reste exécutable (le prochain 25 décembre existe), mais la réponse de
    # référence a été écrite pour un autre hiver : c'est T7, pas T1.
    findings = detect_temporal_decay(
        task("Find a Mexico hotel with deals for December 25-26.", "Booking"), today=TODAY
    )
    (f,) = [x for x in findings if x.signal and x.signal.startswith("yearless_date")]
    assert f.category is Category.EVAL_BRITTLENESS
    assert f.severity is Severity.MEDIUM and f.severity < Severity.HIGH


def test_une_date_relative_est_classee_en_fragilite_d_evaluation():
    findings = detect_temporal_decay(task("Find the latest iPhone model", "Apple"), today=TODAY)
    (f,) = [x for x in findings if x.signal == "relative_date"]
    assert f.category is Category.EVAL_BRITTLENESS
    assert f.severity is Severity.LOW


def test_une_date_future_ne_declenche_rien_par_defaut():
    findings = detect_temporal_decay(
        task("Book a hotel in Paris from December 20 to December 27, 2027", "Booking"), today=TODAY
    )
    assert not [f for f in findings if f.signal and f.signal.startswith("past_date")]


def test_une_date_future_peut_etre_consignee_avec_sa_peremption():
    findings = detect_temporal_decay(
        task("Book a hotel in Paris from December 20 to December 27, 2027", "Booking"),
        today=TODAY,
        emit_info=True,
    )
    (f,) = [x for x in findings if x.signal == "future_date_valid"]
    assert f.severity is Severity.INFO
    assert f.risk == 0.0
    assert f.details["expires_after"].startswith("2027-12")


def test_le_verdict_change_avec_la_date_d_analyse():
    # La même tâche, analysée à deux dates : c'est la définition même du decay.
    t = task("Book a flight departing on March 5, 2026", "Google Flights")
    assert signals(detect_temporal_decay(t, today=dt.date(2026, 1, 1))) == set()
    assert "past_date_transactional" in signals(detect_temporal_decay(t, today=TODAY))


def test_une_tache_sans_date_ne_produit_aucun_constat():
    assert detect_temporal_decay(task("Find a vegetarian lasagna recipe", "Allrecipes"), today=TODAY) == []
