#!/usr/bin/env bash
# Campagne « matrice des canaux » — 15 sites × 4 cellules × 2 passes.
#
# Ce script est la moitié de la valeur du travail. La mesure qu'il remplace — quatre
# observations de navigateur saisies à la main — n'est pas rejetée parce qu'elle est
# petite, mais parce qu'elle n'est pas rejouable : personne ne peut la contredire sans
# refaire à la main ce que son auteur a fait à la main. Celle-ci doit tourner sans son
# auteur.
#
# LE PLAN
#
#                         moteur : aucun (client HTTP)   moteur : navigateur réel
#   origine : datacenter        http_datacenter              browser_datacenter
#   origine : résidentielle     http_residential             browser_residential
#
# Chaque contraste ne fait varier qu'un facteur. Comparer les deux colonnes à origine
# fixée isole le moteur de rendu ; comparer les deux lignes à moteur fixé isole l'origine
# réseau. La campagne du 15/08 ne disposait que d'une case et demie, et ne pouvait donc
# attribuer ses écarts à l'un plutôt qu'à l'autre.
#
# OÙ TOURNE QUOI
#
#   cellules résidentielles : sur une machine derrière un abonnement grand public.
#   cellules datacenter     : sur un serveur loué, ou via .github/workflows/
#                             matrice_canaux_datacenter.yml (runner GitHub Actions).
#
#   Le script ne devine pas où il tourne : c'est `--cellules` qui le dit. Un canal mal
#   déclaré vaut moins que pas de canal du tout.
#
# USAGE
#
#   ./experiments/campagne_matrice.sh --passe 1 --cellules residentielles
#   ./experiments/campagne_matrice.sh --passe 2 --cellules residentielles   # ≥ 1 h après
#   ./experiments/campagne_matrice.sh --passe 1 --cellules datacenter
#   ./experiments/campagne_matrice.sh --analyse
#
# POLITESSE — ces réglages ne sont pas négociables, ils vivent dans matrice_lib.py :
#   une requête par hôte toutes les 2 s (15 s pour arxiv.org, qui déclare Crawl-delay: 15),
#   séquentiellement, une seule navigation de document par site et par passe, aucun clic,
#   aucune saisie, aucun contournement de protection, aucun réessai sur un code HTTP.

set -euo pipefail

cd "$(dirname "$0")/.."   # racine de benchmark-doctor

PASSE=""
CELLULES=""
ANALYSE=0
ATTENDRE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --passe)     PASSE="$2"; shift 2 ;;
    --cellules)  CELLULES="$2"; shift 2 ;;
    --analyse)   ANALYSE=1; shift ;;
    --attendre)  ATTENDRE=1; shift ;;   # dort une heure avant de commencer (passe 2)
    -h|--help)   sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "option inconnue : $1" >&2; exit 2 ;;
  esac
done

# --------------------------------------------------------------------------------------
# Environnement
# --------------------------------------------------------------------------------------

if [[ ! -x .venv/bin/python ]]; then
  echo "→ création de l'environnement"
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.11
    uv pip install --quiet requests pillow
  else
    echo "uv est absent. Installe-le (https://astral.sh/uv) ou crée .venv à la main" >&2
    exit 1
  fi
fi
PY=.venv/bin/python

RUNS=runs/matrice
HAR=runs/har
CAPTURES=runs/captures
mkdir -p "$RUNS" "$HAR" "$CAPTURES"

# --------------------------------------------------------------------------------------
# Analyse seule
# --------------------------------------------------------------------------------------

if [[ "$ANALYSE" == "1" ]]; then
  $PY experiments/analyse_matrice.py --runs "$RUNS" --sortie "$RUNS/analyse.json"
  exit 0
fi

if [[ -z "$PASSE" || -z "$CELLULES" ]]; then
  echo "il faut --passe N et --cellules {residentielles|datacenter}, ou --analyse" >&2
  exit 2
fi

# La répétabilité n'est pas un supplément d'âme : sans deuxième passe, un écart entre
# canaux ne se distingue pas d'une fluctuation du site. Une heure est le minimum retenu.
if [[ "$ATTENDRE" == "1" ]]; then
  echo "→ attente d'une heure avant la passe $PASSE (répétabilité)"
  sleep 3600
fi

echo "=== passe $PASSE — cellules $CELLULES — $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="

case "$CELLULES" in
  residentielles)
    $PY experiments/collecte_http.py \
        --cellule http_residential --passe "$PASSE" \
        --sortie "$RUNS/http_residential_p$PASSE.json"

    $PY experiments/collecte_navigateur.py \
        --cellule browser_residential --passe "$PASSE" \
        --sortie "$RUNS/browser_residential_p$PASSE.json" \
        --har "$HAR" --captures "$CAPTURES"

    $PY experiments/reparer_corps_reseau.py \
        "$RUNS/browser_residential_p$PASSE.json" --har "$HAR"
    ;;

  datacenter)
    # Chrome refuse de démarrer sous le bac à sable sur beaucoup de serveurs loués : les
    # espaces de noms utilisateur y sont désactivés. `--no-sandbox` est un réglage de
    # confinement du processus, sans effet sur l'empreinte réseau ni sur l'User-Agent :
    # il ne déguise pas le client, il le laisse démarrer.
    export AGENT_BROWSER_ARGS="${AGENT_BROWSER_ARGS:---no-sandbox}"

    $PY experiments/collecte_http.py \
        --cellule http_datacenter --passe "$PASSE" \
        --sortie "$RUNS/http_datacenter_p$PASSE.json"

    if command -v agent-browser >/dev/null 2>&1; then
      $PY experiments/collecte_navigateur.py \
          --cellule browser_datacenter --passe "$PASSE" \
          --sortie "$RUNS/browser_datacenter_p$PASSE.json" \
          --har "$HAR" --captures "$CAPTURES"

      $PY experiments/reparer_corps_reseau.py \
          "$RUNS/browser_datacenter_p$PASSE.json" --har "$HAR"
    else
      echo "agent-browser absent : cellule browser_datacenter NON mesurée." >&2
      echo "  npm install -g agent-browser@0.34.0 && agent-browser install --with-deps" >&2
      echo "  (sur Linux sans écran, installer aussi xvfb pour le mode --headed)" >&2
    fi
    ;;

  *)
    echo "cellules inconnues : $CELLULES" >&2
    exit 2 ;;
esac

agent-browser close --all >/dev/null 2>&1 || true

echo "=== passe $PASSE terminée — $(date -u '+%Y-%m-%dT%H:%M:%SZ') ==="
ls -la "$RUNS"
