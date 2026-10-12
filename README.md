# Plan marathon — générateur Streamlit

Application Streamlit qui génère un plan d'entraînement marathon personnalisé à partir
d'un objectif de temps, en reproduisant la logique du fichier Excel
`Than_than_plan_Marathon_18_10_26.xlsx`.

- **Éditeur** : modifie la structure du plan (semaines, séances, types d'allure, paramètres).
  Chaque modification est enregistrée immédiatement dans un fichier Excel local.
- **Coureur** : saisit son objectif, consulte son plan avec ses allures et l'exporte
  (lecture seule).

---

## 1. Installation et lancement

```bash
cd plan_marathon_app
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

L'application s'ouvre sur http://localhost:8501.

### Codes d'accès

Copie `.streamlit/secrets.toml.example` en `.streamlit/secrets.toml` et choisis tes codes :

```toml
[access]
editor_code = "mon-code-editeur"
user_code   = "mon-code-coureur"
```

Autre possibilité : les variables d'environnement `PLAN_EDITOR_CODE` et `PLAN_USER_CODE`.

Sans configuration, des **codes de démonstration** sont actifs (`coach-2026` pour l'éditeur,
`coureur-2026` pour le coureur) et un avertissement s'affiche côté éditeur.
**Change-les avant de partager l'application.**

### Tests

```bash
pip install pytest
python -m pytest -q
```

Les tests vérifient que les allures, temps de référence, dates et temps spécifiques
sont identiques aux valeurs calculées par l'Excel pour l'objectif 3:29:00.

---

## 2. Logique de calcul (reprise de l'Excel)

| Allure | Formule Excel | Calcul Python | Exemple 3:29:00 |
|---|---|---|---|
| A1 · marathon | `H4 = (C4/E4)*60` | 42,2 ÷ objectif (min) × 60 | 12,11 km/h · 4'57"/km |
| Endurance | `M5 = H4*85%` | A1 × 0,85 | 10,30 km/h · 5'50"/km |
| A2 · semi | `M7 = H4*105%` | A1 × 1,05 | 12,72 km/h · 4'43"/km |
| A3 · 10 km | `M8 = M7*105%` | A2 × 1,05 | 13,36 km/h · 4'30"/km |
| A4 · 5 km | `M9 = M8*105%` | A3 × 1,05 | 14,02 km/h · 4'17"/km |
| Sprint | `M10 = M9*120%` | A4 × 1,20 | 16,83 km/h · 3'34"/km |

- Allure (min/km) = `60 ÷ vitesse` (colonne N de l'Excel, en minutes décimales).
- Temps de référence : marathon = 42,2 × A1, semi = 21,1 × A2, 10 km = 10 × A3,
  5 km = 5 × A4 (colonne Q et bloc L14:N19).
- Temps spécifique d'une séance = km spécifiques × allure (colonne « mn » : `H9 = F9*G9`).
- Séance **JOUR J** : sa durée est l'objectif (`E11 = D4`).
- Dates : la dernière semaine est celle de la course ; chaque semaine commence le lundi,
  7 jours avant la suivante (`B14 = B10 - 7`).
- La distance marathon reste **42,2 km** comme dans l'Excel (cellule C4).

Les ratios sont centralisés dans `marathon/config.py` (`PACE_DEFINITIONS`) : pour en
modifier un ou ajouter un type d'allure, c'est le seul endroit à changer.

### Ajustements par rapport au fichier d'origine

- JOUR J : la colonne km indiquait 21,11 alors que les calculs utilisent 42,2 → 42,2.
- S5 : la ligne « s1 » vide en double n'est pas reprise.
- S5 s1 : le texte indique « 1000 A2 » mais la formule pointe vers A3 → A3 conservé,
  avec une remarque.
- Colonne O de l'Excel (allures saisies à la main) : l'application arrondit à la seconde
  la plus proche, d'où 4'30" pour A3 au lieu de 4'29" (valeur exacte : 4'29,5").

---

## 3. Utilisation

**Tous les rôles** : champ « Objectif marathon » (hh:mm:ss, ou h:mm), allures calculées,
plan par semaine ou en tableau complet, ordre chronologique ou compte à rebours (comme l'Excel),
export **Excel** (onglets Plan, Allures, Objectif) et **CSV** (séparateur `;`, compatible Excel FR).

**Éditeur**, onglet *Édition* :
- modifier n'importe quelle cellule d'une semaine ; ajouter une séance avec le « + » du tableau,
  la supprimer en cochant sa ligne puis la corbeille ;
- choisir un **type d'allure** : allure, vitesse et temps spécifique se recalculent selon
  l'objectif en cours ;
- *Durée (semaines)* → *Appliquer la durée* : allonge le plan (6, 8, 12…) en ajoutant des
  semaines squelettes au début (3 séances A2 / A1 / A2, comme S0) ou le raccourcit en retirant
  les plus anciennes. La fin du plan et la semaine de course ne bougent pas ;
- menu *Actions* de chaque semaine : insérer une semaine avant, dupliquer, supprimer ;
- *Phase* : libellé libre de la semaine (ex. « Assimilation / récupération »).

**Éditeur**, onglet *Paramètres* : nom du plan, date du marathon, objectif proposé par défaut,
téléchargement / restauration du fichier de données, réinitialisation au modèle Excel.

---

## 4. Persistance

- Fichier : `data/plan_marathon.xlsx` (créé au premier lancement à partir du modèle Excel,
  rechargé à chaque démarrage). Dossier modifiable avec la variable `PLAN_DATA_DIR`.
- Onglets : `parametres`, `semaines`, `seances` — lisibles et modifiables dans Excel.
- Écriture atomique ; la version précédente est conservée en `data/plan_marathon.bak.xlsx`.
- Le fichier ne contient que la **structure** du plan : les allures sont recalculées à
  l'affichage, donc un même plan sert à tous les coureurs, chacun avec son objectif.

> **Hébergement** : sur Streamlit Community Cloud, le disque n'est pas permanent (il est
> réinitialisé à chaque redéploiement ou mise en veille). Télécharge régulièrement le fichier
> de données depuis *Paramètres* et restaure-le si besoin, ou héberge l'application sur un
> serveur ou un PC avec un disque permanent.

---

## 5. Structure du code

```
plan_marathon_app/
├── app.py                  # Interface Streamlit (connexion, objectif, plan, édition, paramètres)
├── marathon/
│   ├── config.py           # Ratios, types d'allure, schéma des données
│   ├── paces.py            # Calcul des allures, conversions de temps
│   ├── template.py         # Plan par défaut transcrit de l'Excel (S0 → S7)
│   ├── plan.py             # Modèle du plan + opérations (semaines, séances, colonnes calculées)
│   ├── storage.py          # Sauvegarde/chargement Excel, exports Excel/CSV
│   └── auth.py             # Codes d'accès et rôles
├── tests/test_calculs.py   # Tests de non-régression vs valeurs de l'Excel
├── data/                   # Fichier de données (créé automatiquement)
├── .streamlit/config.toml  # Thème
└── .streamlit/secrets.toml.example
```
