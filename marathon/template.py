"""
Plan par défaut : transcription fidèle du fichier Excel d'origine.

Dans l'Excel, les semaines sont listées en compte à rebours (S7 = semaine de la
course en haut, S0 en bas). Ici elles sont rangées dans l'ordre chronologique :
la position 0 correspond à S0, la dernière à S7 (semaine du marathon).

Colonne « tps k » de l'Excel -> champ `allure` :
    =N5 -> Endurance   =N6 / =F4 / =E4/F11 -> A1   =N7 -> A2
    =N8 -> A3          =N9 -> A4              =N10 -> Sprint

Ajustements (signalés dans le README) :
  * JOUR J : km saisis à 21,11 dans l'Excel alors que F11 = 42,2 -> 42,2.
  * S5 : la ligne « s1 » vide en double (ligne 18) n'est pas reprise.
  * S7 s1/s2 : la colonne « dont spécifique km » (4 et 2) devient `km_spe`,
    ce qui permet de recalculer la colonne « mn » (H9 = F9 × G9).
"""

from __future__ import annotations

from .config import DEFAULT_SETTINGS, RACE_DAY_LABEL

PHASE_TAPER = "Assimilation / récupération / refaire du jus !"


def _s(seance, km_env="", duree_env="", contenu="", allure=None, km_spe=None, remarque=""):
    """Raccourci pour décrire une séance."""
    return {
        "seance": seance,
        "km_env": km_env,
        "duree_env": duree_env,
        "contenu": contenu,
        "km_spe": km_spe,
        "allure": allure,
        "remarque": remarque,
    }


# Une entrée par semaine, de la plus ancienne (S0) à la semaine de course (S7).
TEMPLATE_WEEKS: list[dict] = [
    {   # S0 — 24/08 (lignes 44-46 de l'Excel) : squelette sans contenu
        "phase": "",
        "sessions": [
            _s("s1", allure="A2"),
            _s("s2", allure="A1"),
            _s("s3", allure="A2"),
        ],
    },
    {   # S1 (« S01 ») — 31/08 (lignes 39-42)
        "phase": "",
        "sessions": [
            _s("s1", "13", "1:10", '2x(6x30"/30")', "Sprint"),
            _s("s2", "10", "1:00", "2x1000 A2", "A2"),
            _s("s3", "12", "1:10", "2x2000 A1 r=1000", "A1"),
            _s("s4", "22", "2:00", "endurance dont 2x1000 A1 r=2", "A1"),
        ],
    },
    {   # S2 (« S02 ») — 07/09 (lignes 34-37)
        "phase": "",
        "sessions": [
            _s("s1", "13", "1:15", '8x30"/30"', "Sprint"),
            _s("s2", "14", "1:20", "2x2000 A1 r=1000", "A1"),
            _s("s3", "10", "1:00", "end", "Endurance"),
            _s("s4", "25", "2:20", "end dont 2x20' A2", "A2"),
        ],
    },
    {   # S3 (« S03 ») — 14/09 (lignes 29-32)
        "phase": "Endurance",
        "sessions": [
            _s("s1", "16", "1:35", "2000 A2", "A2"),
            _s("s2", "16", "1:30", "3x2000 A1", "A1"),
            _s("s3"),
            _s("s4", "25 à 27", "2:30", "end dont 2x30' A1", "A1",
               remarque="Remplacé par le Trail des Légendes (26 km)"),
        ],
    },
    {   # S4 (« S04 ») — 21/09 (lignes 24-27)
        "phase": "",
        "sessions": [
            _s("s1", "12", "1:10", "endurance", "Endurance"),
            _s("s2", "12", "1:10", "2x2000 A1", "A1"),
            _s("s3", "14", "1:20", "2x2000 A2 (r1500)", "A2"),
            _s("s4", "27 à 30", "2:45", "end dont 1h à 1h15 A1", "A1"),
        ],
    },
    {   # S5 (« S05 ») — 28/09 (lignes 18-22)
        "phase": "",
        "sessions": [
            _s("s1", "16", "1:30", "2000 A1+1000 A2+2000 A1", "A3",
               remarque="Formule Excel sur A3 (réf. : 2000 m A1 + 1000 m A3 + 2000 m A1)"),
            _s("s2", "12", "1:10", "end", "Endurance"),
            _s("s3", "12", "1:05", "8000 A1", "A1"),
            _s("s4", "25 à 30", "2:45", "end dont 2 ou 3x30 A1 (selon forme)", "A1"),
        ],
    },
    {   # S6 — 05/10 (lignes 13-16)
        "phase": PHASE_TAPER,
        "sessions": [
            _s("s1", allure="A1"),
            _s("s2", allure="A1"),
            _s("s3"),
            _s("s4", "20 à 25", "2:00", "end dont 2x30 A1", "A1"),
        ],
    },
    {   # S7 — 12/10, semaine du marathon (lignes 9-11)
        "phase": PHASE_TAPER,
        "sessions": [
            _s("s1", "10", "1:00", "dont 4 km A1", "A1", km_spe=4.0),
            _s("s2", "5", "0:30", "dont 2 km A1", "A1", km_spe=2.0),
            _s(RACE_DAY_LABEL, "42.2", "", "Marathon", "A1", km_spe=42.2,
               remarque="Durée = objectif (calculée automatiquement)"),
        ],
    },
]

TEMPLATE_SETTINGS: dict[str, str] = {
    **DEFAULT_SETTINGS,
    "plan_name": "Plan Marathon 18/10/26",
    "race_date": "2026-10-18",
    "default_objective": "03:29:00",
}
