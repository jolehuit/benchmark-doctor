"""Tests de la chaîne complète L1 et de l'outillage d'évaluation.

Le dernier bloc verrouille les chiffres publiés dans le mémoire : si un détecteur est
modifié, ces tests échouent et signalent qu'un tableau du mémoire doit être recalculé.
Ils sont ignorés si le corpus n'est pas présent (il n'est pas versionné).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from benchmark_doctor import run_l1
from benchmark_doctor.cli import (
    ABLATIONS,
    _prf,
    classify_patch_reason,
    load_ground_truth,
    main,
)
from benchmark_doctor.models import Severity, Task
from benchmark_doctor.parsers.webvoyager import load_webvoyager

TODAY = dt.date(2026, 8, 15)
RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
CORPUS = RAW / "webvoyager_original.jsonl"
PATCHES = RAW / "magnitude_patches.json"

needs_corpus = pytest.mark.skipif(
    not CORPUS.exists(), reason="corpus WebVoyager absent (data/raw non versionné)"
)


# -- chaîne L1 -------------------------------------------------------------------------


def test_run_l1_produit_un_bulletin_date_et_canalise():
    tasks = [
        Task(task_id="Booking--1", question="Book a hotel from March 20 to 27, 2024", site="Booking"),
        Task(task_id="Allrecipes--1", question="Find a lasagna recipe", site="Allrecipes"),
    ]
    health = run_l1(tasks, today=TODAY, source="mémoire")
    assert health.n_tasks == 2
    assert health.generated_at == TODAY
    assert [c.value for c in health.channels] == ["static"]
    assert len(health.flagged(Severity.HIGH)) == 1
    assert health.summary()["source"] == "mémoire"


def test_les_trois_detecteurs_l1_contribuent_au_meme_verdict():
    task = Task(
        task_id="Apple--9",
        question="Log in and buy the iPhone 13 Pro on March 2, 2024",
        site="Apple",
    )
    health = run_l1([task], today=TODAY)
    detectors = {f.detector for f in health.verdicts[0].findings}
    assert detectors == {"l1_temporal", "l1_sideeffect", "l1_reference"}


def test_le_meme_corpus_analyse_a_deux_dates_donne_deux_taux():
    # Pas de verbe d'action ici : seule la date doit faire basculer le verdict.
    tasks = [Task(task_id="B--1", question="Search for a hotel in Paris for March 20, 2026", site="Booking")]
    assert run_l1(tasks, today=dt.date(2026, 1, 1)).flag_rate(Severity.HIGH) == 0.0
    assert run_l1(tasks, today=TODAY).flag_rate(Severity.HIGH) == 1.0


# -- ground truth ----------------------------------------------------------------------


def test_load_ground_truth_lit_le_format_magnitude(tmp_path):
    path = tmp_path / "patches.json"
    path.write_text(json.dumps({
        "Booking--8": {"reason": "Dates are outdated", "prev": "a", "new": "b"},
        "Apple--20": {"reason": "This phone is no longer sold", "prev": "a"},
    }))
    gt = load_ground_truth(path)
    assert gt["Booking--8"]["action"] == "edit" and gt["Booking--8"]["category"] == "temporal"
    assert gt["Apple--20"]["action"] == "delete" and gt["Apple--20"]["category"] == "content_drift"


def test_load_ground_truth_lit_une_liste_d_identifiants(tmp_path):
    path = tmp_path / "impossible.json"
    path.write_text(json.dumps(["Allrecipes--3", "Allrecipes--16"]))
    gt = load_ground_truth(path)
    assert set(gt) == {"Allrecipes--3", "Allrecipes--16"}
    assert all(v["category"] == "unlabelled" for v in gt.values())


def test_load_ground_truth_lit_un_jsonl_de_taches_exclues(tmp_path):
    path = tmp_path / "outdated.jsonl"
    path.write_text(json.dumps({"id": "Apple--7", "ques": "x", "web_name": "Apple"}) + "\n")
    assert set(load_ground_truth(path)) == {"Apple--7"}


@pytest.mark.parametrize(
    "reason,expected",
    [
        ("The dates are outdated, updated to 2026", "temporal"),
        ("This phone is no longer sold", "content_drift"),
        ("Cannot actually reserve a hotel", "impossible"),
        ("It's very ambiguous what 'updates' means here", "ambiguity"),
        ("", "other"),
    ],
)
def test_classification_des_motifs_de_patch(reason, expected):
    assert classify_patch_reason(reason) == expected


def test_prf_est_nul_quand_rien_n_est_signale():
    assert _prf(set(), {"a"}) == (0.0, 0.0, 0.0)


# -- ablation --------------------------------------------------------------------------


def test_les_politiques_d_ablation_sont_ordonnees_par_permissivite():
    tasks = load_webvoyager(CORPUS) if CORPUS.exists() else [
        Task(task_id="B--1", question="Book a hotel from March 20 to 27, 2024", site="Booking"),
        Task(task_id="A--1", question="Find the latest iPhone 15 Pro price", site="Apple"),
    ]
    health = run_l1(tasks, today=TODAY)
    counts = {
        key: sum(1 for v in health.verdicts if predicate(v))
        for key, (_, predicate) in ABLATIONS.items()
    }
    assert counts["v2_contextual"] <= counts["v2_reference_strict"] <= counts["v2_reference"]


# -- verrouillage des chiffres publiés -------------------------------------------------


@needs_corpus
def test_le_corpus_de_reference_compte_643_taches():
    assert len(load_webvoyager(CORPUS)) == 643


@needs_corpus
@pytest.mark.skipif(not PATCHES.exists(), reason="patch-set Magnitude absent")
def test_les_chiffres_l1_publies_sont_reproductibles():
    # Chiffres du mémoire, mesurés au 15/08/2026 sur les 643 tâches d'origine.
    # Toute modification d'un détecteur L1 doit faire échouer ce test.
    tasks = load_webvoyager(CORPUS)
    health = run_l1(tasks, today=TODAY)
    truth = set(load_ground_truth(PATCHES))

    v1 = {v.task.task_id for v in health.verdicts if ABLATIONS["v1_naive"][1](v)}
    v2 = {v.task.task_id for v in health.verdicts if ABLATIONS["v2_contextual"][1](v)}
    assert len(truth) == 121
    assert len(v1) == 121
    assert len(v2) == 73

    p1, r1, _ = _prf(v1, truth)
    p2, r2, _ = _prf(v2, truth)
    assert round(100 * p1) == 65 and round(100 * r1) == 65
    assert round(100 * p2) == 97 and round(100 * r2) == 59

    sites = health.by_site(Severity.HIGH)
    assert sites["Google Flights"]["flagged"] == 33
    assert sites["Booking"]["flagged"] == 33


@needs_corpus
def test_la_commande_scan_s_execute(capsys, tmp_path):
    out = tmp_path / "health.json"
    code = main(["scan", str(CORPUS), "--today", "2026-08-15", "--json", str(out)])
    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["summary"]["n_tasks"] == 643
    assert payload["summary"]["channels"] == ["static"]
    assert "Booking--8" in {t["task_id"] for t in payload["tasks"]}
