"""
Tests de non-régression : les calculs doivent reproduire les valeurs du fichier Excel
d'origine (objectif 3:29:00). Lancer avec :  python -m pytest -q
"""

import io
import math
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from marathon.paces import compute_paces, format_pace, parse_objective, parse_km_range, parse_duration_minutes  # noqa: E402
from marathon.plan import computed_columns, full_plan_table, week_summary, sessions_equal, clean_sessions  # noqa: E402
from marathon import storage  # noqa: E402

OBJ = 3 * 3600 + 29 * 60  # 3:29:00, cellule D4

# Valeurs calculées par Excel (lecture du classeur en data_only).
EXCEL = {
    "Endurance": (10.297607655502391, 5.826596041260107),
    "A1": (12.114832535885167, 4.95260663507109),
    "A2": (12.720574162679426, 4.716768223877229),
    "A3": (13.356602870813399, 4.492160213216407),
    "A4": (14.02443301435407, 4.278247822110864),
    "Sprint": (16.829319617224883, 3.5652065184257204),
}


@pytest.mark.parametrize("code", EXCEL)
def test_allures_identiques_a_excel(code):
    p = compute_paces(OBJ)[code]
    kmh, dec = EXCEL[code]
    assert math.isclose(p.kmh, kmh, rel_tol=1e-12)
    assert math.isclose(p.min_per_km, dec, rel_tol=1e-12)


def test_temps_de_reference():
    paces = compute_paces(OBJ)
    assert math.isclose(paces["A1"].ref_time_minutes, 209.0, rel_tol=1e-12)       # Q6 / M19
    assert math.isclose(paces["A2"].ref_time_minutes, 99.52380952380953, rel_tol=1e-12)  # Q7 / M17
    assert math.isclose(paces["A3"].ref_time_minutes, 44.921602132164075, rel_tol=1e-12)  # Q8 / M16
    assert math.isclose(paces["A4"].ref_time_minutes, 21.39123911055432, rel_tol=1e-12)   # Q9 / M14


def test_format_allure_colonne_O():
    paces = compute_paces(OBJ)
    assert format_pace(paces["A1"].min_per_km) == "4'57\""
    assert format_pace(paces["Endurance"].min_per_km) == "5'50\""
    assert format_pace(paces["A2"].min_per_km) == "4'43\""
    assert format_pace(paces["A4"].min_per_km) == "4'17\""
    assert format_pace(paces["Sprint"].min_per_km) == "3'34\""


@pytest.mark.parametrize("txt,sec", [("03:29:00", OBJ), ("3:29:00", OBJ), ("3:29", OBJ), ("3h29", OBJ),
                                     ("2:59:59", 2 * 3600 + 59 * 60 + 59)])
def test_parse_objectif(txt, sec):
    assert parse_objective(txt) == sec


@pytest.mark.parametrize("txt", ["", "abc", "3:75:00", "0:30:00", "12:00:00"])
def test_parse_objectif_invalide(txt):
    with pytest.raises(ValueError):
        parse_objective(txt)


def test_utilitaires():
    assert parse_km_range("25 à 30") == (25, 30)
    assert parse_km_range("21,1") == (21.1, 21.1)
    assert parse_km_range("") is None
    assert parse_duration_minutes("1:10") == 70
    assert parse_duration_minutes("2h45") == 165


def test_modele_par_defaut():
    plan = storage.default_plan()
    assert plan.n_weeks == 8
    assert plan.week_start(0) == date(2026, 8, 24)   # A44
    assert plan.week_start(5) == date(2026, 9, 28)   # A18
    assert plan.week_start(7) == date(2026, 10, 12)  # B10
    table = full_plan_table(plan, compute_paces(OBJ), OBJ)
    s7 = table[table["semaine"] == "S7"].reset_index(drop=True)
    # H9 = F9*G9 = 19.81 ; H10 = 9.905 ; H11 = 209
    assert math.isclose(s7.loc[0, "temps_spe_min"], 19.81042654028436, rel_tol=1e-9)
    assert math.isclose(s7.loc[1, "temps_spe_min"], 9.90521327014218, rel_tol=1e-9)
    assert math.isclose(s7.loc[2, "temps_spe_min"], 209.0, rel_tol=1e-9)
    assert s7.loc[2, "duree_env"] == "3:29:00"       # E11 = D4
    s1 = table[table["semaine"] == "S1"]
    assert list(s1["allure"]) == ["Sprint", "A2", "A1", "A1"]


def test_allure_recalculee_pour_une_seance_ajoutee():
    plan = storage.default_plan()
    wid = plan.weeks["week_id"].iloc[1]
    sub = plan.sessions_of(wid)
    sub.loc[len(sub)] = {"seance": None, "km_env": "8", "duree_env": "0:45", "contenu": "footing",
                         "km_spe": None, "allure": "A4", "remarque": None}
    plan2 = plan.replace_week_sessions(wid, sub)
    new = plan2.sessions_of(wid)
    assert new["seance"].iloc[-1] == "s5"              # numérotation automatique
    comp = computed_columns(new, compute_paces(3 * 3600), 3 * 3600)
    assert comp["allure_txt"].iloc[-1] == format_pace(compute_paces(3 * 3600)["A4"].min_per_km)


def test_operations_semaines():
    plan = storage.default_plan()
    p12 = plan.resize(12)
    assert p12.n_weeks == 12
    # la fin du plan (semaine de course) est conservée
    last = p12.weeks.sort_values("position")["week_id"].iloc[-1]
    assert "JOUR J" in list(p12.sessions_of(last)["seance"])
    p6 = plan.resize(6)
    assert p6.n_weeks == 6
    dup = plan.duplicate_week(plan.weeks["week_id"].iloc[2])
    assert dup.n_weeks == 9
    assert sessions_equal(dup.sessions_of(dup.weeks["week_id"].iloc[2]), plan.sessions_of(plan.weeks["week_id"].iloc[2]))


def test_sauvegarde_et_rechargement(tmp_path):
    path = tmp_path / "plan.xlsx"
    plan = storage.default_plan().resize(10).with_settings(default_objective="03:15:00")
    storage.save_plan(plan, path)
    storage.save_plan(plan, path)  # 2e sauvegarde -> crée le .bak
    loaded = storage.load_plan(path)
    assert loaded.n_weeks == 10
    assert loaded.settings["default_objective"] == "03:15:00"
    assert list(loaded.weeks["week_id"]) == list(plan.weeks["week_id"])
    for wid in plan.weeks["week_id"]:
        assert sessions_equal(loaded.sessions_of(wid), plan.sessions_of(wid))
    assert (tmp_path / "plan.bak.xlsx").exists()


def test_exports():
    plan = storage.default_plan()
    paces = compute_paces(OBJ)
    table = full_plan_table(plan, paces, OBJ)
    xlsx = storage.export_excel(table, paces, OBJ, plan)
    sheets = pd.read_excel(io.BytesIO(xlsx), sheet_name=None)
    assert set(sheets) == {"Plan", "Allures", "Objectif"}
    assert len(sheets["Plan"]) == len(plan.sessions)
    csv = storage.export_csv(table).decode("utf-8-sig")
    assert csv.splitlines()[0].startswith("Semaine;Du;Au")


def test_clean_idempotent():
    plan = storage.default_plan()
    once = clean_sessions(plan.sessions_of(plan.weeks["week_id"].iloc[3]))
    assert sessions_equal(once, clean_sessions(once))


def test_resume_semaine():
    plan = storage.default_plan()
    table = full_plan_table(plan, compute_paces(OBJ), OBJ)
    s3 = week_summary(table[table["semaine"] == "S3"])
    assert (s3.km_min, s3.km_max) == (57, 59)
