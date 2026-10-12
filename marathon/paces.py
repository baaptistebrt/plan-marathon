"""
Calcul des allures et utilitaires de conversion de temps.

Module « pur » (aucune dépendance à Streamlit) : il peut être testé et réutilisé
tel quel, par exemple dans un script ou un notebook.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .config import (
    MARATHON_KM,
    OBJECTIVE_MAX_SECONDS,
    OBJECTIVE_MIN_SECONDS,
    PACE_DEFINITIONS,
)


# ----------------------------------------------------------------------------
# Conversion de durées
# ----------------------------------------------------------------------------
_HMS_RE = re.compile(r"^\s*(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?\s*$")
_HMIN_RE = re.compile(r"^\s*(\d{1,2})\s*h\s*(\d{1,2})?\s*(?:m|mn|min|')?\s*(\d{1,2})?\s*(?:s|\")?\s*$",
                      re.IGNORECASE)
_MIN_RE = re.compile(r"^\s*(\d{1,3})\s*(?:'|mn|min|minutes?)\s*$", re.IGNORECASE)


def parse_objective(text: str) -> int:
    """Convertit un objectif saisi en secondes.

    Formats acceptés : « 03:29:00 », « 3:29:00 », « 3:29 » (h:mm), « 3h29 », « 3h29'30 ».
    Lève ValueError avec un message en français si la saisie est invalide.
    """
    if text is None or not str(text).strip():
        raise ValueError("Saisis un objectif au format hh:mm:ss (ex. 03:29:00).")
    raw = str(text).strip()
    m = _HMS_RE.match(raw)
    if m:
        h, mnt, s = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    else:
        m = _HMIN_RE.match(raw)
        if not m:
            raise ValueError(f"« {raw} » n'est pas un temps valide. Format attendu : hh:mm:ss (ex. 03:29:00).")
        h, mnt, s = int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)
    if mnt >= 60 or s >= 60:
        raise ValueError("Les minutes et les secondes doivent être inférieures à 60.")
    seconds = h * 3600 + mnt * 60 + s
    if not OBJECTIVE_MIN_SECONDS <= seconds <= OBJECTIVE_MAX_SECONDS:
        raise ValueError(
            f"Objectif hors limites : il doit être compris entre {format_hms(OBJECTIVE_MIN_SECONDS)} "
            f"et {format_hms(OBJECTIVE_MAX_SECONDS)}."
        )
    return seconds


def parse_duration_minutes(text) -> float | None:
    """Convertit une durée « approximative » de séance en minutes, ou None si illisible.

    Accepte « 1:10 » (h:mm), « 1:10:00 », « 1h10 », « 70' », « 70 min », ou un nombre de minutes.
    """
    if text is None or (isinstance(text, float) and math.isnan(text)):
        return None
    raw = str(text).strip()
    if not raw:
        return None
    m = _HMS_RE.match(raw)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3) or 0) / 60
    m = _HMIN_RE.match(raw)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2) or 0) + int(m.group(3) or 0) / 60
    m = _MIN_RE.match(raw)
    if m:
        return float(m.group(1))
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def parse_km_range(text) -> tuple[float, float] | None:
    """Lit un kilométrage approximatif : « 12 » -> (12, 12), « 25 à 30 » -> (25, 30)."""
    if text is None or (isinstance(text, float) and math.isnan(text)):
        return None
    numbers = re.findall(r"\d+(?:[.,]\d+)?", str(text))
    if not numbers:
        return None
    values = [float(n.replace(",", ".")) for n in numbers[:2]]
    return (min(values), max(values))


def format_hms(seconds: float) -> str:
    """3 h 29 min 0 s -> « 3:29:00 »."""
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def format_pace(min_per_km: float | None) -> str:
    """Allure décimale -> « 4'57" » (arrondi à la seconde la plus proche)."""
    if min_per_km is None or (isinstance(min_per_km, float) and math.isnan(min_per_km)):
        return ""
    total = int(round(min_per_km * 60))
    m, s = divmod(total, 60)
    return f"{m}'{s:02d}\""


def format_minutes(minutes: float | None) -> str:
    """Durée en minutes -> « 20 min » ou « 3h29 » (au-delà d'une heure)."""
    if minutes is None or (isinstance(minutes, float) and math.isnan(minutes)):
        return ""
    total = int(round(minutes))
    if total < 60:
        return f"{total} min"
    h, m = divmod(total, 60)
    return f"{h}h{m:02d}"


# ----------------------------------------------------------------------------
# Calcul des allures
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Pace:
    """Allure calculée pour un objectif donné."""

    code: str
    label: str
    description: str
    excel_formula: str
    kmh: float                 # vitesse (colonne M de l'Excel)
    min_per_km: float          # allure en minutes décimales (colonne N de l'Excel)
    ref_km: float | None
    ref_label: str | None

    @property
    def pace_str(self) -> str:
        return format_pace(self.min_per_km)

    @property
    def ref_time_minutes(self) -> float | None:
        """Temps prédit sur la distance de référence (colonne Q de l'Excel)."""
        return None if self.ref_km is None else self.ref_km * self.min_per_km


def marathon_speed_kmh(objective_seconds: int) -> float:
    """Vitesse A1 = (C4 / E4) * 60, avec E4 = objectif en minutes."""
    return MARATHON_KM / (objective_seconds / 60) * 60


def compute_paces(objective_seconds: int) -> dict[str, Pace]:
    """Calcule toutes les allures à partir de l'objectif marathon (en secondes).

    Les ratios sont chaînés comme dans l'Excel (A3 = A2 × 1,05, etc.).
    """
    speeds: dict[str, float] = {"A1": marathon_speed_kmh(objective_seconds)}
    for d in PACE_DEFINITIONS:
        if d.base is not None:
            speeds[d.code] = speeds[d.base] * d.factor

    return {
        d.code: Pace(
            code=d.code,
            label=d.label,
            description=d.description,
            excel_formula=d.excel_formula,
            kmh=speeds[d.code],
            min_per_km=60 / speeds[d.code],
            ref_km=d.ref_km,
            ref_label=d.ref_label,
        )
        for d in PACE_DEFINITIONS
    }
