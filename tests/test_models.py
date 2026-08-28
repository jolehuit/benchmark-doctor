"""Tests des types partagés : sévérité, canal, score de stabilité, agrégations."""

from __future__ import annotations

import datetime as dt

import pytest

from benchmark_doctor.models import (
    GRADE_THRESHOLDS,
    SEVERITY_WEIGHTS,
    BenchmarkHealth,
    Category,
    Channel,
    Finding,
    Severity,
    Task,
    TaskVerdict,
)

TODAY = dt.date(2026, 8, 15)


def make_task(task_id: str = "Booking--1", question: str = "Trouver un hôtel", site: str = "Booking") -> Task:
    return Task(task_id=task_id, question=question, site=site, start_url="https://example.org/")


def make_finding(**kwargs) -> Finding:
    base = dict(
        category=Category.TEMPORAL,
        severity=Severity.HIGH,
        confidence=0.9,
        evidence="March 20, 2024",
        detector="l1_temporal",
        observed_at=TODAY,
    )
    base.update(kwargs)
    return Finding(**base)  # type: ignore[arg-type]


# -- taxonomie -------------------------------------------------------------------------


def test_category_codes_couvrent_t1_a_t8():
    codes = [c.code for c in Category]
    assert codes == [f"T{i}" for i in range(1, 9)]


def test_category_from_code_accepte_plusieurs_ecritures():
    assert Category.from_code("T2") is Category.CONTENT_DRIFT
    assert Category.from_code("content_drift") is Category.CONTENT_DRIFT
    assert Category.from_code("T2_content_drift") is Category.CONTENT_DRIFT
    with pytest.raises(ValueError):
        Category.from_code("T9")


# -- sévérité --------------------------------------------------------------------------


def test_severite_est_ordonnee_et_ponderee():
    assert Severity.LOW < Severity.MEDIUM < Severity.HIGH < Severity.CRITICAL
    assert Severity.INFO.weight == 0.0
    assert Severity.CRITICAL.weight == 1.0
    assert Severity.HIGH >= Severity.HIGH


# -- canal -----------------------------------------------------------------------------


def test_le_canal_distingue_les_observations_reseau():
    # Un 402 vu depuis un datacenter et un 200 vu depuis un navigateur cloud sont deux
    # constats distincts : le canal doit donc être porté par le constat lui-même.
    datacenter = make_finding(channel=Channel.HTTP_DATACENTER, detector="l2_liveness",
                              category=Category.ACCESS_DENIED, evidence="HTTP 402")
    cloud = make_finding(channel=Channel.BROWSER_CLOUD, detector="l2_liveness",
                         category=Category.ACCESS_DENIED, evidence="HTTP 200",
                         severity=Severity.INFO, confidence=0.9)
    assert datacenter.channel is not cloud.channel
    assert datacenter.channel.is_networked and cloud.channel.is_networked
    assert not Channel.STATIC.is_networked


def test_les_constats_l1_sont_statiques_par_defaut():
    assert make_finding().channel is Channel.STATIC


# -- constat ---------------------------------------------------------------------------


def test_finding_rejette_une_confiance_hors_bornes():
    with pytest.raises(ValueError):
        make_finding(confidence=1.4)


def test_finding_exige_un_detecteur_tracable():
    with pytest.raises(ValueError):
        make_finding(detector="")


def test_finding_accepte_les_valeurs_textuelles_et_fait_un_aller_retour_json():
    f = Finding(
        category="T1_temporal",
        severity="high",
        confidence=0.8,
        evidence="March 2024",
        detector="l1_temporal",
        channel="static",
        observed_at="2026-08-15",
    )
    assert f.category is Category.TEMPORAL and f.severity is Severity.HIGH
    assert Finding.from_dict(f.to_dict()) == f


def test_le_risque_combine_severite_et_confiance():
    assert make_finding(severity=Severity.HIGH, confidence=0.8).risk == pytest.approx(0.6)
    # Un constat très grave mais peu sûr pèse moins qu'un constat moyen et certain.
    peu_sur = make_finding(severity=Severity.CRITICAL, confidence=0.2)
    certain = make_finding(severity=Severity.MEDIUM, confidence=0.9)
    assert peu_sur.risk < certain.risk


def test_la_couche_se_deduit_du_nom_du_detecteur():
    assert make_finding(detector="l1_temporal").layer == "L1"
    assert make_finding(detector="l3_llm").layer == "L3"


# -- verdict ---------------------------------------------------------------------------


def test_verdict_vide_est_parfaitement_stable():
    v = TaskVerdict(task=make_task(), evaluated_at=TODAY)
    assert v.stability_score == 1.0
    assert v.grade == "A"
    assert not v.is_flagged()


def test_le_verdict_propage_l_identifiant_de_tache():
    v = TaskVerdict(task=make_task("ESPN--3"), evaluated_at=TODAY)
    v.add(make_finding(task_id=None))
    assert v.findings[0].task_id == "ESPN--3"


def test_le_score_de_stabilite_retient_le_pire_constat():
    v = TaskVerdict(task=make_task(), evaluated_at=TODAY)
    v.add(make_finding(severity=Severity.LOW, confidence=0.4))
    v.add(make_finding(severity=Severity.HIGH, confidence=0.8))  # risque 0,6
    assert v.stability_score == pytest.approx(0.4)
    assert v.grade == "C"


# -- échelle de notes : verrouillage explicite -----------------------------------------
#
# Le dépôt a porté deux échelles concurrentes (0,85/0,60/0,35 dans `models`,
# 0,75/0,50/0,25 dans `scoring`) jusqu'au 16/08/2026 sans qu'aucun test ne s'en aperçoive :
# les assertions existantes portaient toutes sur des scores où les deux échelles
# s'accordent. Les trois tests qui suivent verrouillent ce que les précédents laissaient
# passer — la valeur des bornes, le sens de la comparaison, et l'unicité de la table.


def test_les_bornes_de_notes_sont_derivees_de_la_severite():
    # Chaque frontière est « un constat de cette sévérité tenu pour certain ».
    # Si quelqu'un réintroduit 0,85 / 0,60 / 0,35, ce test tombe.
    assert GRADE_THRESHOLDS == {
        "A": 1.0 - SEVERITY_WEIGHTS["low"],
        "B": 1.0 - SEVERITY_WEIGHTS["medium"],
        "C": 1.0 - SEVERITY_WEIGHTS["high"],
        "D": 0.0,
    }
    assert (GRADE_THRESHOLDS["A"], GRADE_THRESHOLDS["B"], GRADE_THRESHOLDS["C"]) == (0.75, 0.50, 0.25)


@pytest.mark.parametrize(
    "severity, attendu",
    [(Severity.LOW, "B"), (Severity.MEDIUM, "C"), (Severity.HIGH, "D")],
)
def test_un_constat_certain_fait_perdre_la_note_correspondante(severity, attendu):
    # La comparaison est STRICTE : la frontière appartient à la note inférieure. Un
    # constat `low` certain donne un score de 0,75 exactement et doit coûter le A, sans
    # quoi « A = rien au-delà du niveau low » serait faux au point où la phrase se joue.
    v = TaskVerdict(task=make_task(), evaluated_at=TODAY)
    v.add(make_finding(severity=severity, confidence=1.0))
    assert v.stability_score == pytest.approx(1.0 - SEVERITY_WEIGHTS[severity.value])
    assert v.grade == attendu


def test_les_deux_implementations_de_la_note_s_accordent_partout():
    # `models.TaskVerdict.grade` et `scoring.grade_for` sont deux chemins de code vers la
    # même décision. Ils ont divergé une fois ; ce test rend une nouvelle divergence
    # impossible à committer en silence.
    from benchmark_doctor.scoring import GRADE_THRESHOLDS as SCORING_THRESHOLDS
    from benchmark_doctor.scoring import grade_for

    assert SCORING_THRESHOLDS is GRADE_THRESHOLDS  # une seule table, pas une copie
    for i in range(0, 1001):
        score = i / 1000
        v = TaskVerdict(task=make_task(), evaluated_at=TODAY)
        if score < 1.0:
            v.add(make_finding(severity=Severity.CRITICAL, confidence=round(1.0 - score, 3)))
        assert v.grade == grade_for(v.stability_score), score


def test_le_seuil_de_flag_est_explicite():
    v = TaskVerdict(task=make_task(), evaluated_at=TODAY)
    v.add(make_finding(severity=Severity.MEDIUM, confidence=0.6))
    assert not v.is_flagged(Severity.HIGH)
    assert v.is_flagged(Severity.MEDIUM)


def test_le_verdict_enregistre_les_canaux_observes():
    v = TaskVerdict(task=make_task(), evaluated_at=TODAY)
    v.add(make_finding(channel=Channel.BROWSER_CLOUD, detector="l2_liveness"))
    assert Channel.STATIC in v.channels and Channel.BROWSER_CLOUD in v.channels


# -- bulletin --------------------------------------------------------------------------


def _health() -> BenchmarkHealth:
    h = BenchmarkHealth(benchmark="webvoyager", generated_at=TODAY)
    dead = TaskVerdict(task=make_task("Booking--1", site="Booking"), evaluated_at=TODAY)
    dead.add(make_finding(severity=Severity.HIGH, confidence=0.95, signal="past_date_transactional"))
    aging = TaskVerdict(task=make_task("ArXiv--1", site="ArXiv"), evaluated_at=TODAY)
    aging.add(make_finding(severity=Severity.LOW, confidence=0.5, signal="past_date_archival"))
    healthy = TaskVerdict(task=make_task("ArXiv--2", site="ArXiv"), evaluated_at=TODAY)
    h.verdicts.extend([dead, aging, healthy])
    return h


def test_le_bulletin_agrege_taux_notes_et_categories():
    h = _health()
    assert h.n_tasks == 3
    assert len(h.flagged(Severity.HIGH)) == 1
    assert h.flag_rate(Severity.HIGH) == pytest.approx(1 / 3)
    assert h.category_prevalence()["T1_temporal"] == 2
    assert h.grade_distribution()["A"] == 2


def test_le_bulletin_ventile_par_site_et_trie_par_taux():
    rows = _health().by_site(Severity.HIGH)
    assert list(rows)[0] == "Booking"
    assert rows["Booking"]["flagged"] == 1 and rows["ArXiv"]["flagged"] == 0


def test_une_politique_explicite_remplace_le_seuil():
    # Rejouer une politique arbitraire sur une analyse déjà calculée : c'est ce qui rend
    # l'ablation des détecteurs gratuite.
    h = _health()
    tout = h.flag_rate(predicate=lambda v: bool(v.findings))
    assert tout == pytest.approx(2 / 3)


def test_le_resume_consigne_la_politique_et_le_canal():
    summary = _health().summary(Severity.HIGH, policy="v2 contextuel")
    assert summary["flag_policy"] == "v2 contextuel"
    assert summary["channels"] == ["static"]
    assert summary["n_tasks"] == 3


def test_le_rapport_json_est_serialisable():
    import json

    payload = _health().to_dict()
    assert json.loads(json.dumps(payload))["summary"]["n_tasks"] == 3


def test_task_refuse_un_identifiant_vide():
    with pytest.raises(ValueError):
        Task(task_id="", question="x")
