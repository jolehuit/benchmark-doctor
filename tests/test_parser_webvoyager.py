"""Tests du lecteur WebVoyager."""

from __future__ import annotations

import json

import pytest

from benchmark_doctor.parsers.webvoyager import (
    WebVoyagerParseError,
    load_webvoyager,
    load_webvoyager_index,
    parse_webvoyager_record,
)

RECORD = {
    "web_name": "Booking",
    "id": "Booking--8",
    "ques": "Get the hotel with highest review score in Chennai for 20/12/2023 - 21/12/2023.",
    "web": "https://www.booking.com/",
}


def test_normalise_les_champs_webvoyager():
    task = parse_webvoyager_record(RECORD)
    assert task.task_id == "Booking--8"
    assert task.site == "Booking"
    assert task.start_url == "https://www.booking.com/"
    assert task.question.startswith("Get the hotel")
    assert task.raw["ques"] == RECORD["ques"]


def test_accepte_les_noms_de_champs_des_forks():
    task = parse_webvoyager_record(
        {"task_id": "OM2W--1", "confirmed_task": "Trouver un vol", "website": "Google Flights"},
        benchmark="online_mind2web",
    )
    assert task.task_id == "OM2W--1"
    assert task.question == "Trouver un vol"
    assert task.benchmark == "online_mind2web"


def test_refuse_un_enregistrement_sans_identifiant():
    with pytest.raises(WebVoyagerParseError):
        parse_webvoyager_record({"ques": "sans identifiant"})


def test_refuse_un_enregistrement_sans_enonce():
    with pytest.raises(WebVoyagerParseError):
        parse_webvoyager_record({"id": "X--1"})


def test_lit_un_jsonl_avec_lignes_vides(tmp_path):
    path = tmp_path / "corpus.jsonl"
    path.write_text(json.dumps(RECORD) + "\n\n" + json.dumps({**RECORD, "id": "Booking--9"}) + "\n")
    tasks = load_webvoyager(path)
    assert [t.task_id for t in tasks] == ["Booking--8", "Booking--9"]


def test_lit_aussi_un_tableau_json(tmp_path):
    # Plusieurs forks publient leur corpus en .json plutôt qu'en .jsonl.
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps([RECORD]))
    assert len(load_webvoyager(path)) == 1


def test_index_detecte_les_identifiants_dupliques(tmp_path):
    path = tmp_path / "corpus.jsonl"
    path.write_text(json.dumps(RECORD) + "\n" + json.dumps(RECORD) + "\n")
    with pytest.raises(WebVoyagerParseError):
        load_webvoyager_index(path)


def test_index_permet_la_comparaison_entre_forks(tmp_path):
    original = tmp_path / "a.jsonl"
    fork = tmp_path / "b.jsonl"
    original.write_text(json.dumps(RECORD) + "\n" + json.dumps({**RECORD, "id": "Booking--9"}) + "\n")
    fork.write_text(json.dumps({**RECORD, "ques": "énoncé réécrit"}) + "\n")
    a, b = load_webvoyager_index(original), load_webvoyager_index(fork, benchmark="magnitude")
    assert set(a) - set(b) == {"Booking--9"}
    assert a["Booking--8"].question != b["Booking--8"].question
