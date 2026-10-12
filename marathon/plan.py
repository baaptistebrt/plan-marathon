"""
Modèle de données du plan d'entraînement et opérations de structure.

Un `Plan` contient :
  * `weeks`    : une ligne par semaine (week_id, position, phase), position 0 = première semaine ;
  * `sessions` : une ligne par séance (voir config.SESSION_COLUMNS) ;
  * `settings` : nom du plan, date de course, objectif par défaut.

Le plan ne stocke QUE la structure (ce que saisit l'éditeur). Les allures, dates et
temps spécifiques sont recalculés à l'affichage à partir de l'objectif en cours :
un même plan sert ainsi à tous les coureurs, chacun avec son propre objectif.

Toutes les opérations renvoient un NOUVEAU Plan (pas de mutation en place), ce qui
évite les effets de bord entre les reruns de Streamlit.
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pandas as pd

from .config import (
    DEFAULT_SETTINGS,
    PACE_CODES,
    PACE_LABELS,
    RACE_DAY_LABEL,
    SESSION_COLUMNS,
    SESSION_INPUT_COLUMNS,
    SESSION_TEXT_COLUMNS,
    SKELETON_WEEK,
    WEEK_COLUMNS,
)
from .paces import Pace, format_hms, format_minutes, format_pace, parse_duration_minutes, parse_km_range


# ----------------------------------------------------------------------------
# Normalisation des valeurs saisies
# ----------------------------------------------------------------------------
def _is_missing(value) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def clean_text(value) -> str:
    """Texte propre : '' pour une valeur vide, nombres entiers sans « .0 »."""
    if _is_missing(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def clean_number(value) -> float:
    """Nombre (float) ou NaN. Accepte la virgule décimale française."""
    if _is_missing(value) or (isinstance(value, str) and not value.strip()):
        return math.nan
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return math.nan


def clean_pace_code(value) -> str | None:
    """Code d'allure valide (Endurance, A1…) ou None. Tolère casse et libellés longs."""
    if _is_missing(value):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    for code in PACE_CODES:
        if raw.lower() == code.lower() or raw.lower() == PACE_LABELS[code].lower():
            return code
    # « A1 · marathon », « allure 1 » …
    m = re.match(r"^\s*(?:a|allure\s*)([1-4])\b", raw, re.IGNORECASE)
    if m:
        return f"A{m.group(1)}"
    if raw.lower().startswith("end"):
        return "Endurance"
    if raw.lower().startswith("sprint"):
        return "Sprint"
    return None


def clean_sessions(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise un tableau de séances (types, valeurs vides, libellés automatiques).

    Fonction idempotente : clean_sessions(clean_sessions(x)) == clean_sessions(x).
    Les séances sans libellé reçoivent automatiquement « sN » (N = plus grand numéro + 1).
    """
    out = pd.DataFrame(index=range(len(df)))
    src = df.reset_index(drop=True)
    for col in SESSION_INPUT_COLUMNS:
        values = src[col] if col in src.columns else [None] * len(src)
        if col in SESSION_TEXT_COLUMNS:
            out[col] = pd.Series([clean_text(v) for v in values], dtype=object)
        elif col == "km_spe":
            out[col] = pd.Series([clean_number(v) for v in values], dtype="float64")
        elif col == "allure":
            out[col] = pd.Series([clean_pace_code(v) for v in values], dtype=object)

    # Numérotation automatique des séances sans libellé.
    numbers = [int(m.group(1)) for v in out["seance"] if (m := re.fullmatch(r"[sS](\d+)", v))]
    next_n = max(numbers, default=0) + 1
    for i in out.index:
        if not out.at[i, "seance"]:
            out.at[i, "seance"] = f"s{next_n}"
            next_n += 1
    return out


def sessions_equal(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    """Compare deux tableaux de séances après normalisation (NaN == NaN)."""
    ca, cb = clean_sessions(a), clean_sessions(b)
    if len(ca) != len(cb):
        return False
    to_records = lambda d: [  # noqa: E731
        tuple(None if _is_missing(v) else v for v in row) for row in d[SESSION_INPUT_COLUMNS].itertuples(index=False)
    ]
    return to_records(ca) == to_records(cb)


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


# ----------------------------------------------------------------------------
# Le plan
# ----------------------------------------------------------------------------
@dataclass
class Plan:
    weeks: pd.DataFrame
    sessions: pd.DataFrame
    settings: dict = field(default_factory=lambda: dict(DEFAULT_SETTINGS))

    # ---- construction ------------------------------------------------------
    @classmethod
    def from_week_list(cls, weeks: list[dict], settings: dict | None = None) -> "Plan":
        """Construit un plan à partir d'une liste [{phase, sessions: [...]}, …] (ordre chronologique)."""
        week_rows, session_frames = [], []
        for pos, w in enumerate(weeks):
            wid = _new_id()
            week_rows.append({"week_id": wid, "position": pos, "phase": w.get("phase", "")})
            sess = clean_sessions(pd.DataFrame(w.get("sessions", []), columns=SESSION_INPUT_COLUMNS))
            sess.insert(0, "week_id", wid)
            sess.insert(1, "ordre", range(len(sess)))
            session_frames.append(sess)
        sessions = (pd.concat(session_frames, ignore_index=True) if session_frames
                    else pd.DataFrame(columns=SESSION_COLUMNS))
        return cls(pd.DataFrame(week_rows, columns=WEEK_COLUMNS), sessions[SESSION_COLUMNS],
                   {**DEFAULT_SETTINGS, **(settings or {})}).normalized()

    def normalized(self) -> "Plan":
        """Renumérote positions et ordres, supprime les séances orphelines, fixe les types."""
        weeks = self.weeks.copy()
        if weeks.empty:
            weeks = pd.DataFrame(columns=WEEK_COLUMNS)
        weeks["phase"] = [clean_text(v) for v in weeks.get("phase", [])]
        weeks["week_id"] = weeks["week_id"].astype(str)
        weeks = weeks.sort_values("position", kind="stable").reset_index(drop=True)
        weeks["position"] = range(len(weeks))
        weeks = weeks[WEEK_COLUMNS]

        frames = []
        sessions = self.sessions.copy()
        if not sessions.empty:
            sessions["week_id"] = sessions["week_id"].astype(str)
        for wid in weeks["week_id"]:
            sub = sessions[sessions["week_id"] == wid] if not sessions.empty else sessions
            if "ordre" in sub.columns and len(sub):
                sub = sub.sort_values("ordre", kind="stable")
            sub = clean_sessions(sub)
            sub.insert(0, "week_id", wid)
            sub.insert(1, "ordre", range(len(sub)))
            frames.append(sub)
        sessions = (pd.concat(frames, ignore_index=True) if frames
                    else pd.DataFrame(columns=SESSION_COLUMNS))
        sessions["km_spe"] = sessions["km_spe"].astype("float64")
        settings = {**DEFAULT_SETTINGS, **{k: clean_text(v) for k, v in self.settings.items()}}
        return Plan(weeks, sessions[SESSION_COLUMNS].reset_index(drop=True), settings)

    # ---- lecture -------------------------------------------------------------
    @property
    def n_weeks(self) -> int:
        return len(self.weeks)

    @property
    def race_date(self) -> date:
        try:
            return datetime.strptime(self.settings.get("race_date", ""), "%Y-%m-%d").date()
        except ValueError:
            return datetime.strptime(DEFAULT_SETTINGS["race_date"], "%Y-%m-%d").date()

    @staticmethod
    def week_label(position: int) -> str:
        """Libellé de semaine, comme dans l'Excel : S0, S1, … (dernière = semaine de course)."""
        return f"S{position}"

    def week_start(self, position: int) -> date:
        """Lundi de la semaine : lundi de la semaine de course − 7 j par semaine d'écart (B14 = B10 − 7)."""
        race_monday = self.race_date - timedelta(days=self.race_date.weekday())
        return race_monday - timedelta(weeks=self.n_weeks - 1 - position)

    def week_position(self, week_id: str) -> int:
        return int(self.weeks.loc[self.weeks["week_id"] == week_id, "position"].iloc[0])

    def sessions_of(self, week_id: str) -> pd.DataFrame:
        """Séances d'une semaine (colonnes de saisie uniquement, index 0..n-1)."""
        sub = self.sessions[self.sessions["week_id"] == week_id].sort_values("ordre")
        return sub[SESSION_INPUT_COLUMNS].reset_index(drop=True)

    # ---- modifications (renvoient un nouveau Plan) --------------------------
    def replace_week_sessions(self, week_id: str, new_sessions: pd.DataFrame) -> "Plan":
        sub = clean_sessions(new_sessions)
        sub.insert(0, "week_id", week_id)
        sub.insert(1, "ordre", range(len(sub)))
        others = self.sessions[self.sessions["week_id"] != week_id]
        frames = [f for f in (others, sub) if len(f)]
        sessions = pd.concat(frames, ignore_index=True) if frames else sub
        return Plan(self.weeks.copy(), sessions, dict(self.settings)).normalized()

    def set_phase(self, week_id: str, phase: str) -> "Plan":
        weeks = self.weeks.copy()
        weeks.loc[weeks["week_id"] == week_id, "phase"] = clean_text(phase)
        return Plan(weeks, self.sessions.copy(), dict(self.settings)).normalized()

    def insert_week(self, position: int, sessions: list[dict] | pd.DataFrame | None = None,
                    phase: str = "") -> "Plan":
        """Insère une semaine à `position` (0 = au début, n_weeks = à la fin).

        Sans séances fournies, la semaine reprend le squelette de S0 de l'Excel.
        """
        position = max(0, min(position, self.n_weeks))
        wid = _new_id()
        weeks = self.weeks.copy()
        weeks.loc[weeks["position"] >= position, "position"] += 1
        weeks = pd.concat([weeks, pd.DataFrame([{"week_id": wid, "position": position, "phase": phase}])],
                          ignore_index=True)
        if sessions is None:
            sessions = SKELETON_WEEK
        sub = clean_sessions(pd.DataFrame(sessions) if not isinstance(sessions, pd.DataFrame) else sessions)
        sub.insert(0, "week_id", wid)
        sub.insert(1, "ordre", range(len(sub)))
        frames = [f for f in (self.sessions, sub) if len(f)]
        all_sessions = pd.concat(frames, ignore_index=True) if frames else sub
        return Plan(weeks, all_sessions, dict(self.settings)).normalized()

    def duplicate_week(self, week_id: str) -> "Plan":
        """Insère une copie de la semaine juste AVANT elle (pour allonger un bloc)."""
        pos = self.week_position(week_id)
        phase = self.weeks.loc[self.weeks["week_id"] == week_id, "phase"].iloc[0]
        return self.insert_week(pos, self.sessions_of(week_id), phase)

    def delete_week(self, week_id: str) -> "Plan":
        if self.n_weeks <= 1:
            raise ValueError("Le plan doit contenir au moins une semaine.")
        weeks = self.weeks[self.weeks["week_id"] != week_id].copy()
        sessions = self.sessions[self.sessions["week_id"] != week_id].copy()
        return Plan(weeks, sessions, dict(self.settings)).normalized()

    def resize(self, n_weeks: int) -> "Plan":
        """Ajuste la durée du plan en conservant la fin (affûtage + semaine de course).

        * plus de semaines : ajoute des semaines « squelette » au début ;
        * moins de semaines : retire les semaines les plus anciennes.
        """
        if n_weeks < 1:
            raise ValueError("Le plan doit contenir au moins une semaine.")
        plan = self
        while plan.n_weeks < n_weeks:
            plan = plan.insert_week(0)
        while plan.n_weeks > n_weeks:
            first = plan.weeks.sort_values("position")["week_id"].iloc[0]
            plan = plan.delete_week(first)
        return plan

    def with_settings(self, **changes) -> "Plan":
        return Plan(self.weeks.copy(), self.sessions.copy(), {**self.settings, **changes}).normalized()


# ----------------------------------------------------------------------------
# Tableaux calculés (allures, dates, temps) pour l'affichage et l'export
# ----------------------------------------------------------------------------
def is_race_day(seance: str) -> bool:
    return clean_text(seance).upper().replace(" ", "") == RACE_DAY_LABEL.replace(" ", "")


def computed_columns(sessions: pd.DataFrame, paces: dict[str, Pace], objective_seconds: int) -> pd.DataFrame:
    """Ajoute à des séances les colonnes calculées selon l'objectif en cours.

    * allure_txt / allure_dec / vitesse : allure du type choisi (colonnes N et M de l'Excel) ;
    * temps_spe_min : km spécifiques × allure (colonne H : =F9*G9) ;
    * duree_env : pour la séance « JOUR J », durée = objectif (E11 = D4).
    """
    out = sessions.copy().reset_index(drop=True)
    pace_objs = [paces.get(code) if code else None for code in out["allure"]]
    out["allure_txt"] = [format_pace(p.min_per_km) if p else "" for p in pace_objs]
    out["allure_dec"] = [round(p.min_per_km, 2) if p else math.nan for p in pace_objs]
    out["vitesse"] = [round(p.kmh, 1) if p else math.nan for p in pace_objs]
    temps = []
    for p, km in zip(pace_objs, out["km_spe"]):
        temps.append(km * p.min_per_km if (p is not None and not _is_missing(km)) else math.nan)
    out["temps_spe_min"] = temps
    out["temps_spe"] = [format_minutes(t) if not _is_missing(t) else "" for t in temps]
    out["duree_env"] = [
        format_hms(objective_seconds) if is_race_day(s) and not clean_text(d) else d
        for s, d in zip(out["seance"], out["duree_env"])
    ]
    return out


def full_plan_table(plan: Plan, paces: dict[str, Pace], objective_seconds: int) -> pd.DataFrame:
    """Tableau complet du plan (toutes semaines, ordre chronologique), colonnes calculées incluses."""
    frames = []
    for _, w in plan.weeks.sort_values("position").iterrows():
        pos = int(w["position"])
        sub = computed_columns(plan.sessions_of(w["week_id"]), paces, objective_seconds)
        start = plan.week_start(pos)
        sub.insert(0, "week_id", w["week_id"])
        sub.insert(1, "position", pos)
        sub.insert(2, "semaine", Plan.week_label(pos))
        sub.insert(3, "debut", start)
        sub.insert(4, "fin", start + timedelta(days=6))
        sub.insert(5, "phase", w["phase"])
        frames.append(sub)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


@dataclass(frozen=True)
class WeekSummary:
    km_min: float
    km_max: float
    minutes: float
    n_sessions: int

    @property
    def km_str(self) -> str:
        if self.km_max <= 0:
            return "—"
        fmt = lambda x: f"{x:.1f}".rstrip("0").rstrip(".").replace(".", ",")  # noqa: E731
        if abs(self.km_max - self.km_min) < 0.05:
            return f"≈ {fmt(self.km_min)} km"
        return f"≈ {fmt(self.km_min)}–{fmt(self.km_max)} km"

    @property
    def duration_str(self) -> str:
        return format_minutes(self.minutes) if self.minutes > 0 else "—"


def week_summary(computed_sessions: pd.DataFrame) -> WeekSummary:
    """Volume (km min–max) et durée totale d'une semaine, à partir des colonnes « env. »."""
    km_min = km_max = minutes = 0.0
    for km, dur in zip(computed_sessions["km_env"], computed_sessions["duree_env"]):
        rng = parse_km_range(km)
        if rng:
            km_min += rng[0]
            km_max += rng[1]
        m = parse_duration_minutes(dur)
        if m:
            minutes += m
    return WeekSummary(km_min, km_max, minutes, len(computed_sessions))
