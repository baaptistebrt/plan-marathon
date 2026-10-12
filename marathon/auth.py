"""
Authentification simple par code d'accès, avec deux rôles.

Les codes sont lus, dans cet ordre :
  1. dans `.streamlit/secrets.toml` :
         [access]
         editor_code = "..."
         user_code   = "..."
  2. dans les variables d'environnement PLAN_EDITOR_CODE / PLAN_USER_CODE ;
  3. à défaut, des codes de démonstration (un avertissement est alors affiché à l'éditeur).
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

ROLE_EDITOR = "editeur"
ROLE_USER = "coureur"
ROLE_LABELS = {ROLE_EDITOR: "Éditeur", ROLE_USER: "Coureur (lecture seule)"}

DEMO_EDITOR_CODE = "coach-2026"
DEMO_USER_CODE = "coureur-2026"


@dataclass(frozen=True)
class AccessCodes:
    editor: str
    user: str
    source: str  # "secrets", "env" ou "demo"

    @property
    def is_demo(self) -> bool:
        return self.source == "demo"


def _from_secrets() -> tuple[str, str] | None:
    try:
        import streamlit as st

        access = st.secrets.get("access", {})
        editor, user = access.get("editor_code"), access.get("user_code")
        if editor and user:
            return str(editor), str(user)
    except Exception:  # pas de secrets.toml : ce n'est pas une erreur
        pass
    return None


def load_access_codes() -> AccessCodes:
    codes = _from_secrets()
    if codes:
        return AccessCodes(*codes, source="secrets")
    editor, user = os.environ.get("PLAN_EDITOR_CODE"), os.environ.get("PLAN_USER_CODE")
    if editor and user:
        return AccessCodes(editor, user, source="env")
    return AccessCodes(DEMO_EDITOR_CODE, DEMO_USER_CODE, source="demo")


def role_for_code(code: str, codes: AccessCodes) -> str | None:
    """Rôle correspondant au code saisi, ou None. Comparaison à temps constant."""
    if not code:
        return None
    candidate = code.strip().encode()
    if hmac.compare_digest(candidate, codes.editor.encode()):
        return ROLE_EDITOR
    if hmac.compare_digest(candidate, codes.user.encode()):
        return ROLE_USER
    return None
