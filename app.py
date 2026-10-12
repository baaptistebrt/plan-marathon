"""
Plan marathon — application Streamlit.

Lancement :  streamlit run app.py

Rôles (voir marathon/auth.py) :
  * Éditeur : saisit son objectif, modifie la structure du plan (semaines, séances,
    paramètres) ; chaque modification est enregistrée immédiatement dans data/plan_marathon.xlsx.
  * Coureur : saisit son objectif et consulte / exporte son plan, en lecture seule.

La logique métier (calculs, modèle, stockage) est dans le package `marathon/` ;
ce fichier ne contient que l'interface.
"""

from __future__ import annotations

import html
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from marathon import storage
from marathon.auth import ROLE_EDITOR, ROLE_LABELS, load_access_codes, role_for_code
from marathon.config import DISPLAY_NAMES, PACE_CODES, PACE_LABELS, SESSION_INPUT_COLUMNS
from marathon.paces import Pace, compute_paces, format_hms, format_minutes, parse_objective
from marathon.plan import Plan, computed_columns, full_plan_table, sessions_equal, week_summary

st.set_page_config(page_title="Plan marathon", page_icon="🏃", layout="wide")

# Colonnes calculées affichées à côté des colonnes saisies.
COMPUTED_COLUMNS = ["allure_txt", "vitesse", "temps_spe"]
EDITOR_COLUMN_ORDER = ["seance", "km_env", "duree_env", "contenu", "km_spe", "allure",
                       *COMPUTED_COLUMNS, "remarque"]


# =============================================================================
# Données : chargement (mis en cache tant que le fichier ne change pas) et sauvegarde
# =============================================================================
@st.cache_data(show_spinner=False)
def _load_plan_cached(path: str, mtime_ns: int, size: int) -> Plan:
    # mtime_ns et size servent de clé de cache : toute sauvegarde invalide le cache.
    return storage.load_plan(Path(path))


def get_plan() -> Plan:
    """Plan courant, relu depuis le fichier local (source de vérité partagée)."""
    path = storage.ensure_data_file()
    stat = path.stat()
    return _load_plan_cached(str(path), stat.st_mtime_ns, stat.st_size)


def persist(plan: Plan, message: str) -> bool:
    """Enregistre le plan et prépare la notification. Renvoie False en cas d'échec."""
    try:
        st.session_state["last_saved"] = storage.save_plan(plan)
    except Exception as exc:  # disque plein, droits, fichier ouvert dans Excel sous Windows…
        st.session_state["flash"] = ("error", f"Échec de l'enregistrement : {exc}")
        return False
    # Changer de version force la recréation des tableaux éditables avec les nouvelles données.
    st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
    st.session_state["flash"] = ("success", message)
    return True


def is_editor() -> bool:
    return st.session_state.get("role") == ROLE_EDITOR


# =============================================================================
# Mise en forme
# =============================================================================
def inject_css() -> None:
    st.markdown(
        """
        <style>
          .block-container { padding-top: 2.2rem; padding-bottom: 3rem; }
          [data-testid="stMetricValue"] { font-size: 1.55rem; font-variant-numeric: tabular-nums; }
          .week-meta { color: var(--text-color); opacity: .7; font-size: .9rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def fr_number(x: float, digits: int = 1) -> str:
    return f"{x:.{digits}f}".replace(".", ",")


def display_column_config() -> dict:
    """Configuration commune des colonnes (lecture seule et édition)."""
    cc = st.column_config
    return {
        "semaine": cc.TextColumn(DISPLAY_NAMES["semaine"], width=70),
        "debut": cc.DateColumn(DISPLAY_NAMES["debut"], format="DD/MM", width=70),
        "phase": cc.TextColumn(DISPLAY_NAMES["phase"], width=200),
        "seance": cc.TextColumn(DISPLAY_NAMES["seance"], width=75,
                                help="s1, s2… ou « JOUR J » (durée = objectif, calculée automatiquement)"),
        "km_env": cc.TextColumn(DISPLAY_NAMES["km_env"], width=80,
                                help="Nombre ou fourchette : 12, 25 à 30"),
        "duree_env": cc.TextColumn(DISPLAY_NAMES["duree_env"], width=95, help="Format h:mm, ex. 1:10"),
        "contenu": cc.TextColumn(DISPLAY_NAMES["contenu"], width=270,
                                 help='Ex. : 2x2000 A1 r=1000, 8x30"/30", end dont 2x30\' A1'),
        "km_spe": cc.NumberColumn(DISPLAY_NAMES["km_spe"], min_value=0.0, max_value=60.0, step=0.1,
                                  format="%.1f", width=75,
                                  help="Km courus à l'allure choisie : sert à calculer le temps spécifique"),
        "allure": cc.SelectboxColumn(DISPLAY_NAMES["allure"], options=PACE_CODES,
                                     format_func=lambda c: PACE_LABELS.get(c, c), width=125,
                                     help="L'allure se calcule automatiquement selon l'objectif en cours"),
        "allure_label": cc.TextColumn(DISPLAY_NAMES["allure"], width=125),
        "allure_txt": cc.TextColumn("Allure /km", width=85, disabled=True,
                                    help="Calculée à partir de l'objectif et du type d'allure"),
        "vitesse": cc.NumberColumn("km/h", format="%.1f", width=65, disabled=True),
        "temps_spe": cc.TextColumn("Temps spé.", width=90, disabled=True,
                                   help="Km spécifiques × allure (colonne « mn » de l'Excel)"),
        "remarque": cc.TextColumn(DISPLAY_NAMES["remarque"], width=260),
    }


# =============================================================================
# Connexion
# =============================================================================
def render_login() -> None:
    codes = load_access_codes()
    _, center, _ = st.columns([1, 1.3, 1])
    with center:
        st.title("🏃 Plan marathon")
        st.write("Entre ton code d'accès pour générer ton plan d'entraînement personnalisé "
                 "à partir de ton objectif de temps.")
        with st.form("login", border=True):
            code = st.text_input("Code d'accès", type="password", placeholder="••••••••")
            submitted = st.form_submit_button("Se connecter", type="primary", width="stretch")
        if submitted:
            role = role_for_code(code, codes)
            if role:
                st.session_state["role"] = role
                st.rerun()
            time.sleep(1)  # ralentit les essais en série
            st.error("Code incorrect.")


def logout() -> None:
    for key in ("role", "objective_input"):
        st.session_state.pop(key, None)


def render_sidebar(plan: Plan) -> None:
    with st.sidebar:
        st.markdown(f"### {plan.settings.get('plan_name') or 'Plan marathon'}")
        st.caption(f"Connecté : **{ROLE_LABELS.get(st.session_state.get('role'), '?')}**")
        if is_editor():
            saved = st.session_state.get("last_saved")
            st.caption(f"💾 Sauvegarde automatique : `{storage.DATA_FILE.name}`"
                       + (f" — dernière à {saved:%H:%M:%S}" if saved else ""))
            if load_access_codes().is_demo:
                st.warning("Codes d'accès de démonstration actifs. Définis tes propres codes dans "
                           "`.streamlit/secrets.toml` (voir README).", icon="🔐")
        else:
            st.caption("Plan en lecture seule : saisis ton objectif, consulte et exporte ton plan.")
        st.button("Se déconnecter", on_click=logout, icon=":material/logout:")


# =============================================================================
# Objectif et allures
# =============================================================================
def render_objective(plan: Plan) -> int | None:
    """Champ objectif + indicateurs clés. Renvoie l'objectif en secondes (None si invalide)."""
    if "objective_input" not in st.session_state:
        st.session_state["objective_input"] = plan.settings.get("default_objective", "03:29:00")

    st.title("🏃 " + (plan.settings.get("plan_name") or "Plan marathon"))
    c_obj, c_a1, c_kmh, c_race = st.columns([1.4, 1, 1, 1], vertical_alignment="bottom")
    with c_obj:
        text = st.text_input("🎯 Objectif marathon (hh:mm:ss)", key="objective_input",
                             help="Temps visé sur marathon, ex. 03:29:00. Toutes les allures en découlent.")
    try:
        seconds = parse_objective(text)
    except ValueError as exc:
        st.error(str(exc))
        return None

    a1 = compute_paces(seconds)["A1"]
    c_a1.metric("Allure marathon (A1)", f"{a1.pace_str} /km", border=True)
    c_kmh.metric("Vitesse A1", f"{fr_number(a1.kmh)} km/h", border=True)
    days = (plan.race_date - date.today()).days
    countdown = f"J-{days}" if days > 0 else ("Jour J !" if days == 0 else "Course passée")
    c_race.metric("Course", plan.race_date.strftime("%d/%m/%Y"), countdown,
                  delta_color="off", delta_arrow="off", border=True)
    return seconds


def render_paces(paces: dict[str, Pace]) -> None:
    st.subheader("Tes allures")
    cols = st.columns(len(paces))
    for col, p in zip(cols, paces.values()):
        # La vitesse est affichée dans la pastille grise de la carte.
        col.metric(p.label, f"{p.pace_str} /km", f"{fr_number(p.kmh)} km/h", delta_color="off",
                   delta_arrow="off", help=f"{p.description} — {p.excel_formula}", border=True)
    # Temps de référence (colonne Q / bloc L14:N19 de l'Excel).
    refs = [f"{p.ref_label} **{format_minutes(p.ref_time_minutes)}**" for p in paces.values()
            if p.ref_time_minutes and p.code != "A1"]
    st.caption("Équivalences de temps à ces allures : " + " · ".join(refs))
    with st.expander("Comment sont calculées les allures ? (formules de l'Excel)"):
        st.markdown(
            "La vitesse marathon **A1** est calculée à partir de l'objectif : "
            "`42,2 km ÷ objectif (min) × 60`. Les autres allures appliquent des **ratios fixes "
            "sur la vitesse**, enchaînés comme dans le fichier Excel. L'allure (min/km) vaut `60 ÷ vitesse`."
        )
        st.dataframe(storage.paces_table(paces), hide_index=True, width="stretch")


# =============================================================================
# Plan : consultation (tous les rôles)
# =============================================================================
def readonly_frame(sub: pd.DataFrame) -> pd.DataFrame:
    out = sub.copy()
    out["allure_label"] = [PACE_LABELS.get(c, "") if c else "" for c in out["allure"]]
    return out


def week_header(plan: Plan, position: int, phase: str, summary) -> None:
    start = plan.week_start(position)
    end = start + timedelta(days=6)
    current = start <= date.today() <= end
    badge = "  :orange-badge[Semaine en cours]" if current else ""
    race = "  :red-badge[Course]" if position == plan.n_weeks - 1 and start <= plan.race_date <= end else ""
    left, right = st.columns([3, 2], vertical_alignment="center")
    left.markdown(f"**{Plan.week_label(position)}** · du {start:%d/%m} au {end:%d/%m}{badge}{race}"
                  + (f"  \n<span class='week-meta'>{html.escape(phase)}</span>" if phase else ""),
                  unsafe_allow_html=True)
    parts = [f"{summary.n_sessions} séances"] + [x for x in (summary.km_str, summary.duration_str) if x != "—"]
    right.markdown(f"<div class='week-meta' style='text-align:right'>{' · '.join(parts)}</div>",
                   unsafe_allow_html=True)


def render_exports(plan: Plan, table: pd.DataFrame, paces: dict[str, Pace], seconds: int) -> None:
    stem = f"plan_marathon_{format_hms(seconds).replace(':', 'h', 1).replace(':', 'm', 1)}s_{plan.race_date:%Y%m%d}"
    with st.container(horizontal=True):
        st.download_button("Exporter en Excel", storage.export_excel(table, paces, seconds, plan),
                           file_name=f"{stem}.xlsx", icon=":material/download:", type="primary",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           on_click="ignore")
        st.download_button("Exporter en CSV", storage.export_csv(table), file_name=f"{stem}.csv",
                           mime="text/csv", icon=":material/download:", on_click="ignore")


def render_plan_view(plan: Plan, paces: dict[str, Pace], seconds: int) -> None:
    table = full_plan_table(plan, paces, seconds)
    if table.empty:
        st.info("Le plan ne contient encore aucune séance.")
        return

    total = week_summary(table)
    top_left, top_right = st.columns([3, 2], vertical_alignment="bottom")
    with top_left:
        st.markdown(f"**{plan.n_weeks} semaines** · {total.n_sessions} séances · volume total {total.km_str} "
                    f"· {total.duration_str} de course à pied")
    with top_right:
        render_exports(plan, table, paces, seconds)

    with st.container(horizontal=True):
        mode = st.segmented_control("Affichage", ["Par semaine", "Tableau complet"], default="Par semaine",
                                    key="view_mode", required=True)
        order = st.segmented_control("Ordre", ["Chronologique", "Compte à rebours"], default="Chronologique",
                                     key="view_order", required=True,
                                     help="« Compte à rebours » = semaine de course en premier, comme dans l'Excel")

    config = display_column_config()
    ascending = order != "Compte à rebours"
    if mode == "Tableau complet":
        # Tri par semaine (selon l'ordre choisi) en gardant l'ordre des séances dans chaque semaine.
        df = table.assign(_row=range(len(table)))
        df = readonly_frame(df.sort_values(["position", "_row"], ascending=[ascending, True]))
        cols = ["semaine", "debut", "phase", "seance", "km_env", "duree_env", "contenu", "km_spe",
                "allure_label", *COMPUTED_COLUMNS, "remarque"]
        st.dataframe(df[cols], hide_index=True, width="stretch", column_config=config, placeholder="",
                     height=min(38 * (len(df) + 1), 900))
        return

    cols = ["seance", "km_env", "duree_env", "contenu", "km_spe", "allure_label", *COMPUTED_COLUMNS, "remarque"]
    for position in sorted(table["position"].unique(), reverse=not ascending):
        sub = table[table["position"] == position]
        with st.container(border=True):
            week_header(plan, int(position), sub["phase"].iloc[0], week_summary(sub))
            st.dataframe(readonly_frame(sub)[cols], hide_index=True, width="stretch", column_config=config,
                         placeholder="")


# =============================================================================
# Édition (éditeur uniquement)
# =============================================================================
# Les callbacks relisent toujours le plan depuis le fichier : ils s'exécutent avant le script.
def _cb_insert_week(position: int) -> None:
    persist(get_plan().insert_week(position), "Semaine ajoutée")


def _cb_duplicate_week(week_id: str) -> None:
    persist(get_plan().duplicate_week(week_id), "Semaine dupliquée")


def _cb_delete_week(week_id: str) -> None:
    try:
        persist(get_plan().delete_week(week_id), "Semaine supprimée")
    except ValueError as exc:
        st.session_state["flash"] = ("error", str(exc))


def _cb_resize(n_weeks: int) -> None:
    persist(get_plan().resize(n_weeks), f"Plan ajusté à {n_weeks} semaines")


def _cb_phase(week_id: str, key: str) -> None:
    persist(get_plan().set_phase(week_id, st.session_state.get(key, "")), "Phase enregistrée")


def editor_view(sessions: pd.DataFrame, paces: dict[str, Pace], seconds: int) -> pd.DataFrame:
    """Séances d'une semaine + colonnes calculées (non éditables)."""
    comp = computed_columns(sessions, paces, seconds)
    view = sessions.copy()
    for col in COMPUTED_COLUMNS:
        view[col] = comp[col]
    # Types explicites pour que les colonnes vides restent éditables.
    for col in ("seance", "km_env", "duree_env", "contenu", "remarque", "allure_txt", "temps_spe"):
        view[col] = view[col].astype(object)
    view["allure"] = view["allure"].astype(object)
    view["km_spe"] = view["km_spe"].astype("float64")
    view["vitesse"] = view["vitesse"].astype("float64")
    return view[EDITOR_COLUMN_ORDER]


def render_structure_controls(plan: Plan, version: int) -> None:
    with st.container(border=True):
        st.markdown("**Structure du plan**")
        c_n, c_apply, c_add = st.columns([1, 1.4, 2.4], vertical_alignment="bottom")
        target = c_n.number_input("Durée (semaines)", min_value=1, max_value=52, value=plan.n_weeks,
                                  step=1, key=f"resize_{version}")
        with c_apply:
            diff = int(target) - plan.n_weeks
            with st.popover("Appliquer la durée", disabled=diff == 0, icon=":material/date_range:"):
                if diff > 0:
                    st.write(f"{diff} semaine(s) « squelette » (3 séances A2 / A1 / A2, comme S0 de l'Excel) "
                             "seront ajoutées **au début** du plan. La fin du plan et la semaine de course "
                             "ne bougent pas.")
                else:
                    st.write(f"Les **{-diff} premières semaines** du plan et leurs séances seront supprimées.")
                st.button("Confirmer", type="primary", on_click=_cb_resize, args=(int(target),),
                          key=f"resize_ok_{version}")
        with c_add:
            with st.container(horizontal=True):
                st.button("Semaine au début", icon=":material/add:", on_click=_cb_insert_week, args=(0,),
                          key=f"add_first_{version}")
                st.button("Semaine à la fin", icon=":material/add:", on_click=_cb_insert_week,
                          args=(plan.n_weeks,), key=f"add_last_{version}")
        st.caption("Les dates sont calculées à partir de la date de course : la dernière semaine est celle du "
                   "marathon, chaque semaine précédente commence 7 jours plus tôt.")


def render_week_editor(plan: Plan, week: pd.Series, paces: dict[str, Pace], seconds: int, version: int) -> None:
    week_id, position = week["week_id"], int(week["position"])
    sessions = plan.sessions_of(week_id)
    start = plan.week_start(position)

    with st.container(border=True):
        c_title, c_phase, c_actions = st.columns([1.6, 3, 0.9], vertical_alignment="center")
        c_title.markdown(f"**{Plan.week_label(position)}** · {start:%d/%m} → {start + timedelta(days=6):%d/%m}")
        phase_key = f"phase_{week_id}_{version}"
        c_phase.text_input("Phase", value=week["phase"], key=phase_key, label_visibility="collapsed",
                           placeholder="Phase / objectif de la semaine (facultatif)",
                           on_change=_cb_phase, args=(week_id, phase_key))
        with c_actions.popover("Actions", icon=":material/more_horiz:", width="stretch"):
            st.button("Insérer une semaine avant", icon=":material/add:", on_click=_cb_insert_week,
                      args=(position,), key=f"ins_{week_id}_{version}", width="stretch")
            st.button("Dupliquer (copie insérée avant)", icon=":material/content_copy:",
                      on_click=_cb_duplicate_week, args=(week_id,), key=f"dup_{week_id}_{version}",
                      width="stretch")
            st.divider()
            confirm = st.checkbox("Confirmer la suppression", key=f"cfm_{week_id}_{version}")
            st.button("Supprimer cette semaine", icon=":material/delete:", type="primary",
                      disabled=not confirm or plan.n_weeks <= 1, on_click=_cb_delete_week, args=(week_id,),
                      key=f"del_{week_id}_{version}", width="stretch")

        view = editor_view(sessions, paces, seconds)
        edited = st.data_editor(
            view,
            key=f"editor_{week_id}_{version}_{seconds}",
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            column_config=display_column_config(),
            disabled=COMPUTED_COLUMNS,
            placeholder="",
        )
        # Une modification a eu lieu : on enregistre puis on relance pour recalculer les allures.
        if not sessions_equal(edited[SESSION_INPUT_COLUMNS], view[SESSION_INPUT_COLUMNS]):
            if persist(plan.replace_week_sessions(week_id, edited[SESSION_INPUT_COLUMNS]),
                       f"{Plan.week_label(position)} enregistrée"):
                st.rerun()


def render_editor(plan: Plan, paces: dict[str, Pace], seconds: int) -> None:
    version = st.session_state.setdefault("editor_version", 0)
    st.caption("Chaque modification est **enregistrée automatiquement**. Ajoute une séance avec la ligne « + » "
               "en bas d'un tableau, supprime-la en cochant sa ligne puis la corbeille. Choisis un **type "
               "d'allure** : l'allure, la vitesse et le temps spécifique se calculent selon l'objectif en cours "
               f"(**{format_hms(seconds)}**).")
    render_structure_controls(plan, version)
    for _, week in plan.weeks.sort_values("position").iterrows():
        render_week_editor(plan, week, paces, seconds, version)


# =============================================================================
# Paramètres (éditeur uniquement)
# =============================================================================
def render_settings(plan: Plan) -> None:
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("**Paramètres du plan**")
        with st.form("settings_form", border=True):
            name = st.text_input("Nom du plan", value=plan.settings.get("plan_name", ""))
            race = st.date_input("Date du marathon", value=plan.race_date, format="DD/MM/YYYY")
            default_obj = st.text_input("Objectif proposé par défaut (hh:mm:ss)",
                                        value=plan.settings.get("default_objective", "03:29:00"))
            submitted = st.form_submit_button("Enregistrer", type="primary")
        if submitted:
            try:
                normalized_obj = format_hms(parse_objective(default_obj)).zfill(8)
            except ValueError as exc:
                st.error(str(exc))
            else:
                if persist(plan.with_settings(plan_name=name.strip() or "Plan marathon",
                                              race_date=race.strftime("%Y-%m-%d"),
                                              default_objective=normalized_obj), "Paramètres enregistrés"):
                    st.rerun()

    with right:
        st.markdown("**Sauvegarde des données**")
        with st.container(border=True):
            st.caption(f"Fichier local : `{storage.DATA_FILE}` (la version précédente est gardée en `.bak.xlsx`). "
                       "Télécharge-le régulièrement si l'application est hébergée sur un service dont le disque "
                       "n'est pas permanent.")
            st.download_button("Télécharger le fichier de données", storage.plan_to_bytes(plan),
                               file_name="plan_marathon_donnees.xlsx", icon=":material/save:", on_click="ignore")
            uploaded = st.file_uploader("Restaurer un fichier de données", type=["xlsx"],
                                        key=f"restore_{st.session_state.get('editor_version', 0)}")
            if uploaded is not None and st.button("Restaurer ce fichier", type="primary"):
                try:
                    restored = storage.plan_from_bytes(uploaded.getvalue())
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    if persist(restored, "Données restaurées"):
                        st.rerun()

        with st.popover("Réinitialiser au modèle Excel", icon=":material/restart_alt:"):
            st.write("Remplace tout le plan par le modèle d'origine (S0 → S7 du fichier Excel). "
                     "Les modifications actuelles seront perdues (sauf la sauvegarde `.bak`).")
            ok = st.checkbox("Je confirme")
            if st.button("Réinitialiser", type="primary", disabled=not ok):
                if persist(storage.default_plan(), "Plan réinitialisé"):
                    st.rerun()

        codes = load_access_codes()
        source = {"secrets": "`.streamlit/secrets.toml`", "env": "variables d'environnement",
                  "demo": "codes de démonstration"}[codes.source]
        st.caption(f"🔐 Codes d'accès lus depuis : {source}.")


# =============================================================================
# Page principale
# =============================================================================
def show_flash() -> None:
    flash = st.session_state.pop("flash", None)
    if flash:
        kind, message = flash
        if kind == "error":
            st.error(message)
        else:
            st.toast(message, icon="✅")


def main() -> None:
    inject_css()
    if "role" not in st.session_state:
        render_login()
        return

    plan = get_plan()
    render_sidebar(plan)
    show_flash()

    seconds = render_objective(plan)
    if seconds is None:
        return
    paces = compute_paces(seconds)
    render_paces(paces)

    if is_editor():
        tab_plan, tab_edit, tab_settings = st.tabs(["📅 Plan", "✏️ Édition", "⚙️ Paramètres"], key="main_tabs")
        with tab_plan:
            render_plan_view(plan, paces, seconds)
        with tab_edit:
            render_editor(plan, paces, seconds)
        with tab_settings:
            render_settings(plan)
    else:
        st.subheader("Ton plan")
        render_plan_view(plan, paces, seconds)


main()
