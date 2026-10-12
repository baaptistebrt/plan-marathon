"""
Constantes métier reprises du fichier Excel « Than_than_plan_Marathon_18_10_26.xlsx ».

Toutes les allures sont dérivées de l'allure marathon (A1) par des ratios FIXES
appliqués sur la VITESSE (km/h), exactement comme dans l'Excel :

    H4  = (C4 / E4) * 60          -> vitesse A1 (km/h) = 42,2 km / objectif (min) * 60
    M5  = H4 * 85 %               -> Endurance
    M6  = H4                      -> A1  (allure marathon)
    M7  = H4 * 105 %              -> A2  (allure semi)
    M8  = M7 * 105 %              -> A3  (allure 10 km)
    M9  = M8 * 105 %              -> A4  (allure 5 km)
    M10 = M9 * 120 %              -> Sprint
    N5..N10 = 60 / M5..M10        -> allure en minutes décimales par km (« centièmes »)

Temps de référence (colonne Q et bloc L14:N19 de l'Excel) :
    Q6  = 42,2 * N6  (marathon à A1)     Q7 = 21,1 * N7 (semi à A2)
    Q8  = 10 * N8    (10 km à A3)        Q9 = 5 * N9    (5 km à A4)
"""

from __future__ import annotations

from dataclasses import dataclass

# Distance marathon utilisée par l'Excel (cellule C4). On garde 42,2 et non 42,195
# pour rester strictement fidèle aux calculs du fichier d'origine.
MARATHON_KM: float = 42.2


@dataclass(frozen=True)
class PaceDefinition:
    """Définition d'un type d'allure et de sa relation avec l'allure de base."""

    code: str                 # identifiant stocké dans le plan (ex. "A1")
    label: str                # libellé court affiché
    description: str          # à quoi correspond cette allure
    base: str | None          # allure dont on part (None = A1, calculée depuis l'objectif)
    factor: float             # multiplicateur appliqué à la vitesse de `base`
    excel_formula: str        # formule d'origine, pour la traçabilité
    ref_km: float | None      # distance de référence pour le temps prédit
    ref_label: str | None     # nom de cette distance


# L'ordre de cette liste est l'ordre de calcul ET d'affichage.
PACE_DEFINITIONS: list[PaceDefinition] = [
    PaceDefinition("Endurance", "Endurance", "Footing, sortie longue", "A1", 0.85,
                   "M5 = H4 × 85 %", None, None),
    PaceDefinition("A1", "A1 · marathon", "Allure marathon (objectif)", None, 1.00,
                   "M6 = H4 = 42,2 / objectif(min) × 60", MARATHON_KM, "Marathon"),
    PaceDefinition("A2", "A2 · semi", "Allure semi-marathon", "A1", 1.05,
                   "M7 = H4 × 105 %", 21.1, "Semi"),
    PaceDefinition("A3", "A3 · 10 km", "Allure 10 km", "A2", 1.05,
                   "M8 = M7 × 105 %", 10.0, "10 km"),
    PaceDefinition("A4", "A4 · 5 km", "Allure 5 km", "A3", 1.05,
                   "M9 = M8 × 105 %", 5.0, "5 km"),
    PaceDefinition("Sprint", "Sprint", "Fractionné court (30\"/30\")", "A4", 1.20,
                   "M10 = M9 × 120 %", None, None),
]

PACE_CODES: list[str] = [p.code for p in PACE_DEFINITIONS]
PACE_LABELS: dict[str, str] = {p.code: p.label for p in PACE_DEFINITIONS}

# Bornes raisonnables pour un objectif marathon (en secondes).
OBJECTIVE_MIN_SECONDS = 1 * 3600 + 50 * 60   # 1:50:00
OBJECTIVE_MAX_SECONDS = 8 * 3600             # 8:00:00

# Libellé spécial de la séance de course : sa durée = objectif (cellule E11 = D4).
RACE_DAY_LABEL = "JOUR J"

# ----------------------------------------------------------------------------
# Schéma des données persistées
# ----------------------------------------------------------------------------
# Une ligne par séance. `week_id` relie la séance à sa semaine.
SESSION_COLUMNS: list[str] = [
    "week_id",     # identifiant stable de la semaine
    "ordre",       # ordre de la séance dans la semaine (0, 1, 2…)
    "seance",      # libellé : s1, s2… ou JOUR J
    "km_env",      # kilométrage approximatif (texte : « 12 », « 25 à 30 »)
    "duree_env",   # durée approximative (texte h:mm, ex. « 1:10 »)
    "contenu",     # contenu / partie spécifique (ex. « 2x2000 A1 r=1000 »)
    "km_spe",      # km courus à l'allure spécifique (nombre) -> temps spécifique
    "allure",      # code du type d'allure (Endurance, A1… Sprint) ou vide
    "remarque",    # note libre
]
# Colonnes saisies par l'éditeur (tout sauf les clés techniques).
SESSION_INPUT_COLUMNS: list[str] = [c for c in SESSION_COLUMNS if c not in ("week_id", "ordre")]
SESSION_TEXT_COLUMNS: list[str] = ["seance", "km_env", "duree_env", "contenu", "remarque"]

WEEK_COLUMNS: list[str] = ["week_id", "position", "phase"]

# Libellés affichés dans l'interface et les exports.
DISPLAY_NAMES: dict[str, str] = {
    "semaine": "Semaine",
    "debut": "Du",
    "fin": "Au",
    "phase": "Phase",
    "seance": "Séance",
    "km_env": "Km (env.)",
    "duree_env": "Durée (env.)",
    "contenu": "Contenu / dont spécifique",
    "km_spe": "Km spé.",
    "allure": "Type d'allure",
    "allure_txt": "Allure (min/km)",
    "allure_dec": "Allure (min,cent./km)",
    "vitesse": "Vitesse (km/h)",
    "temps_spe": "Temps spé.",
    "temps_spe_min": "Temps spé. (min)",
    "remarque": "Remarque",
}

# Squelette utilisé pour les semaines ajoutées (repris de la semaine S0 de l'Excel :
# 3 séances avec un type d'allure mais sans contenu, à compléter par l'éditeur).
SKELETON_WEEK: list[dict] = [
    {"seance": "s1", "allure": "A2"},
    {"seance": "s2", "allure": "A1"},
    {"seance": "s3", "allure": "A2"},
]

DEFAULT_SETTINGS: dict[str, str] = {
    "plan_name": "Plan marathon",
    "race_date": "2026-10-18",
    "default_objective": "03:29:00",
}
