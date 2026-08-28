"""L3 : ambiguïté d'un énoncé de tâche (T5, et T6 quand les deux sont indiscernables).

Une tâche ambiguë ne casse pas : elle s'exécute, elle rend une réponse, et c'est le verdict
qui devient arbitraire. « Trouve une recette de lasagnes végétariennes avec plus de 100 avis
et 4,5 étoiles » admet des dizaines de réponses également correctes ; selon celle que
l'agent rapporte, un juge strict compte un échec là où un juge indulgent compte une
réussite. C'est le mode de dégradation le plus silencieux du benchmark, et celui que la
couche statique rate presque complètement (rappel 33 % en v1).

Quatre implémentations interchangeables sont fournies, par coût croissant. Les chiffres
ci-dessous sont ceux de `experiments/ablation_l3_clean.py` (16/08/2026), qui remplace ceux
du banc du 15/08 : ces derniers étaient mesurés avec une rubrique de juge contenant des
énoncés du jeu évalué (problème B1, cf. le commentaire de ``_RUBRIC``). Protocole : 139
tâches annotées, validation croisée à 5 plis stratifiés, seuil calibré sur les plis
d'entraînement par le J de Youden, coût relevé dans ``usage.cost``. Le juge est exécuté cinq
fois et l'on publie sa moyenne, jamais son maximum.

==============  ==================================  ==========  =====  ===============
Backend         Représentation                      F1          AUC    Coût / 643 tâches
==============  ==================================  ==========  =====  ===============
``tfidf``       TF-IDF mots+bigrammes → rég. log.   0,629       0,776  0 $
``minilm``      all-MiniLM-L6-v2 (384 dim) → rég.   0,608       0,732  0 $
``openrouter``  text-embedding-3-small → rég. log.  0,637       0,787  0,0003 $
``llm``         juge gemini-2.5-flash, note 0-1     0,715±0,006 0,772  0,13 $
==============  ==================================  ==========  =====  ===============

Le ``±`` du juge est la dispersion entre les cinq exécutions (même prompt, même température
0). La dispersion entre plis, beaucoup plus large (≈ 0,18), est un fait sur la taille des
plis, pas sur la stabilité du juge ; le tableau du 15/08 publiait la seconde sous
l'apparence de la première.

Ce que la mesure soutient, tests à l'appui dans `experiments/ABLATION_L3.md` : les trois
premières approches sont indiscernables entre elles et ne battent pas une ligne de base qui
ne connaît que le nom du site, donc payer des embeddings n'achète rien ici. Le juge LLM
n'ordonne pas mieux les énoncés (AUC 0,772 contre 0,776 pour TF-IDF) ; ce qu'il apporte est
un point de fonctionnement, puisqu'à rappel identique il produit 4 faux positifs sur 84
négatifs contre 17. C'est un détecteur de haute précision (0,89) et de rappel moyen, et
c'est la seule revendication soutenue : sur le F1 global l'écart avec TF-IDF n'est pas
significatif. Le juge bon marché, lui, est au niveau du hasard (`gemini-2.5-flash-lite`,
rubrique propre : AUC 0,551) ; la performance n'est pas monotone en fonction du prix, et le
backend ``llm`` pointe sur `gemini-2.5-flash`.

Le chiffre du juge reste une borne haute. Le même modèle, même corpus, sans rubrique (prompt
``plain``), tombe à F1 0,565, soit la valeur de la ligne « tout positif » (0,567) :
l'essentiel de sa performance vient de la grille d'annotation qu'on lui transmet, celle-là
même qu'a suivie l'annotateur du jeu de test. Le protocole mesure donc la reproductibilité
d'une grille entre deux modèles, pas la détection de l'ambiguïté. Aucune formulation du
corpus n'est plus dans le prompt (contrôlé par `experiments/check_rubric_leak.py`), mais la
définition l'est, et elle ne peut pas ne pas l'être.

Le backend se choisit par la variable d'environnement ``BDOCTOR_L3_BACKEND`` (défaut :
``tfidf``, le seul qui n'exige ni clé d'API ni dépendance lourde ; ``llm`` est le choix
recommandé dès qu'une clé est disponible et que 0,13 $ par passage est acceptable). Les
trois premiers backends sont des classifieurs supervisés entraînés sur
``data/annotations_ambiguity.json`` : le jeu annoté est une donnée de l'outil, livrée avec
lui, et non un simple artefact d'évaluation. Leur performance est par conséquent une borne
haute, mesurée sur le corpus qui a servi à les définir.

Conséquence à ne jamais publier sans elle : ``build_scorer(fit=True)`` entraîne le
classifieur sur la totalité des 139 annotations, puis la carte de santé le fait scorer les
643 tâches, dont ces 139. Sur cette intersection, la précision apparente du backend
``tfidf`` est de 0,964 ; hors plis elle est de 0,660. Une carte produite avec le backend par
défaut applique donc deux instruments à un même corpus. Seule la valeur hors plis est
publiable, et pour un chiffre destiné au mémoire il faut ``--l3-backend llm`` (problème C13
de la vérification adverse).

Choix de sévérité assumé : un constat d'ambiguïté est émis en ``MEDIUM``, jamais en
``HIGH``. Une tâche ambiguë reste exécutable ; elle corrompt la mesure, pas le run. Le seuil
de flag dur de l'outil (``Severity.HIGH``) reste donc insensible à cette couche, ce qui
évite de faire bouger les taux de decay publiés par la couche L1 en ajoutant une couche dont
la précision hors plis va de 0,66 (backend ``tfidf``, celui par défaut) à 0,89 (juge LLM),
et dont le rappel plafonne à 0,60 dans les deux cas.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from ..models import Category, Channel, Finding, Severity, Task
from .l3_client import DEFAULT_CHAT_MODEL, DEFAULT_EMBED_MODEL, CostLedger, OpenRouterClient

__all__ = [
    "AmbiguityScorer",
    "TfidfScorer",
    "EmbeddingScorer",
    "LlmJudgeScorer",
    "MiniLmEmbedder",
    "OpenRouterEmbedder",
    "AnnotatedSet",
    "load_annotations",
    "build_scorer",
    "detect_ambiguity",
    "run_ambiguity",
    "calibrate_threshold",
    "calibrate_threshold_youden",
    "JUDGE_PROMPTS",
    "DEFAULT_BACKEND",
    "MINILM_MODEL",
]

DETECTOR_NAME = "l3_ambiguity"

#: Backend par défaut : hors ligne et gratuit. Tout autre choix doit être explicite.
DEFAULT_BACKEND = os.environ.get("BDOCTOR_L3_BACKEND", "tfidf").strip().lower()

#: Modèle d'embedding local (384 dimensions).
MINILM_MODEL = os.environ.get("BDOCTOR_L3_MINILM", "sentence-transformers/all-MiniLM-L6-v2")

#: Seuil de décision par défaut si aucune calibration n'a été faite.
DEFAULT_THRESHOLD = 0.5

_ANNOTATIONS = Path(__file__).resolve().parents[2] / "data" / "annotations_ambiguity.json"


@dataclass(frozen=True, slots=True)
class AnnotatedSet:
    """Le jeu de référence étiqueté : énoncés, étiquettes, sites, métadonnées."""

    texts: list[str]
    labels: list[int]
    sites: list[str]
    task_ids: list[str]
    meta: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __len__(self) -> int:
        return len(self.texts)

    @property
    def positive_rate(self) -> float:
        return sum(self.labels) / len(self.labels) if self.labels else 0.0


def load_annotations(path: str | Path | None = None) -> AnnotatedSet:
    """Charge ``data/annotations_ambiguity.json`` (139 tâches WebVoyager étiquetées)."""
    p = Path(path) if path else _ANNOTATIONS
    payload = json.loads(p.read_text(encoding="utf-8"))
    items = payload["items"]
    return AnnotatedSet(
        texts=[i["question"] for i in items],
        labels=[int(i["label"]) for i in items],
        sites=[i["site"] for i in items],
        task_ids=[i["task_id"] for i in items],
        meta={k: v for k, v in payload.items() if k != "items"},
    )


class AmbiguityScorer(Protocol):
    """Contrat commun aux quatre approches comparées.

    ``score`` renvoie une note dans [0, 1] (probabilité pour les classifieurs, note du
    juge pour le LLM) ; la décision binaire est prise à ``threshold``, calibré par
    ``fit`` sur les seules données d'entraînement. Séparer note et seuil est ce qui rend
    les quatre approches comparables : elles sont évaluées sur la même courbe de
    décision, pas sur des conventions internes différentes.
    """

    name: str
    threshold: float

    def fit(self, texts: Sequence[str], labels: Sequence[int]) -> "AmbiguityScorer": ...

    def score(self, texts: Sequence[str]) -> list[float]: ...


def calibrate_threshold(scores: Sequence[float], labels: Sequence[int]) -> float:
    """Seuil maximisant le F1 de la classe positive sur les données fournies.

    À n'appliquer qu'aux plis d'entraînement : calibrer sur le pli de test reviendrait
    à publier une performance impossible à reproduire en exploitation.

    Attention, ce critère dégénère. À une prévalence de 39,6 %, la stratégie « tout
    positif » obtient déjà F1 = 0,567 ; dès que les notes séparent mal les classes, le seuil
    qui maximise le F1 est le plus bas possible et le détecteur déclare tout le corpus
    ambigu (cas mesuré de `gemini-2.5-flash-lite`), car le F1 n'a pas de terme en vrais
    négatifs. Pour toute calibration publiée, préférer :func:`calibrate_threshold_youden`,
    qui ne peut pas choisir la ligne « tout positif » puisqu'elle y vaut J = 0. Cette
    fonction est conservée telle quelle parce qu'elle est l'estimateur qu'utilisent les
    artefacts déjà publiés, et qu'un banc d'ablation doit pouvoir republier ses chiffres.
    """
    candidates = sorted({round(float(s), 4) for s in scores} | {0.5})
    best_threshold, best_f1 = DEFAULT_THRESHOLD, -1.0
    for t in candidates:
        tp = sum(1 for s, y in zip(scores, labels) if s >= t and y == 1)
        fp = sum(1 for s, y in zip(scores, labels) if s >= t and y == 0)
        fn = sum(1 for s, y in zip(scores, labels) if s < t and y == 1)
        if tp == 0:
            continue
        precision = tp / (tp + fp)
        recall = tp / (tp + fn)
        f1 = 2 * precision * recall / (precision + recall)
        if f1 > best_f1:
            best_threshold, best_f1 = t, f1
    return best_threshold


def calibrate_threshold_youden(scores: Sequence[float], labels: Sequence[int]) -> float:
    """Seuil maximisant le J de Youden (``sensibilité + spécificité − 1``, soit TPR − FPR).

    Contrairement à la maximisation du F1, ce critère compte les vrais négatifs : la
    stratégie « tout positif » y vaut exactement J = 0, comme n'importe quelle règle qui
    ignore l'énoncé. Un seuil n'est donc retenu que s'il sépare réellement les deux
    classes, ce qui est la propriété qu'on attend d'une calibration publiée.

    Départage des ex æquo : la médiane des seuils atteignant le J maximal. Avec des notes
    fortement discrétisées (le juge concentre les siennes sur 0,0 · 0,1 · … · 1,0), plusieurs
    seuils consécutifs donnent la même matrice de confusion ; prendre le plus bas biaiserait
    vers le signalement, le plus haut vers le silence, et prendre celui le plus proche de
    0,5 ferait converger artificiellement ce tableau et celui du seuil fixe.

    À n'appliquer qu'aux plis d'entraînement, pour la même raison que ci-dessus.
    """
    candidates = sorted({round(float(s), 4) for s in scores} | {0.5})
    n_pos = sum(1 for y in labels if y == 1)
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        return DEFAULT_THRESHOLD
    best_j = -2.0
    winners: list[float] = []
    for t in candidates:
        tp = sum(1 for s, y in zip(scores, labels) if s >= t and y == 1)
        fp = sum(1 for s, y in zip(scores, labels) if s >= t and y == 0)
        j = tp / n_pos - fp / n_neg
        if j > best_j + 1e-12:
            best_j, winners = j, [t]
        elif abs(j - best_j) <= 1e-12:
            winners.append(t)
    return winners[len(winners) // 2]


class TfidfScorer:
    """Sacs de n-grammes pondérés TF-IDF, puis régression logistique.

    Ligne de base délibérément pauvre : elle ne connaît que les mots de l'énoncé. Si elle
    suffit, alors le signal d'ambiguïté est lexical (« a recipe with… », « find a »,
    « best ») et payer un modèle de langage pour le détecter est une dépense inutile. C'est
    la question que le banc d'ablation doit trancher.
    """

    name = "tfidf+logreg"

    def __init__(self, *, ngram_range: tuple[int, int] = (1, 2), min_df: int = 2, C: float = 1.0) -> None:
        self.threshold = DEFAULT_THRESHOLD
        self._ngram_range = ngram_range
        self._min_df = min_df
        self._C = C
        self._pipeline: Any = None

    def fit(self, texts: Sequence[str], labels: Sequence[int]) -> "TfidfScorer":
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline

        self._pipeline = make_pipeline(
            TfidfVectorizer(
                ngram_range=self._ngram_range,
                min_df=self._min_df,
                sublinear_tf=True,
                strip_accents="unicode",
                lowercase=True,
            ),
            LogisticRegression(C=self._C, class_weight="balanced", max_iter=2000, random_state=0),
        )
        self._pipeline.fit(list(texts), list(labels))
        return self

    def score(self, texts: Sequence[str]) -> list[float]:
        if self._pipeline is None:
            raise RuntimeError("TfidfScorer.fit doit être appelé avant score")
        return [float(p) for p in self._pipeline.predict_proba(list(texts))[:, 1]]

    def top_features(self, k: int = 15) -> list[tuple[str, float]]:
        """Les n-grammes les plus discriminants, pour l'interprétation du mémoire."""
        if self._pipeline is None:
            raise RuntimeError("TfidfScorer.fit doit être appelé avant top_features")
        vectorizer, model = self._pipeline.steps[0][1], self._pipeline.steps[1][1]
        names = vectorizer.get_feature_names_out()
        weights = model.coef_[0]
        order = sorted(range(len(weights)), key=lambda i: -weights[i])
        return [(str(names[i]), round(float(weights[i]), 3)) for i in order[:k]]


class MiniLmEmbedder:
    """Embeddings locaux `all-MiniLM-L6-v2` (384 dim), sans réseau ni coût marginal."""

    name = "minilm-384"
    dim = 384

    def __init__(self, model_name: str = MINILM_MODEL, *, batch_size: int = 64) -> None:
        self._model_name = model_name
        self._batch_size = batch_size
        self._model: Any = None
        self.ledger = CostLedger(label="minilm-local")

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model

    def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        import time

        started = time.perf_counter()
        model = self._load()
        vectors = model.encode(
            list(texts), batch_size=self._batch_size, show_progress_bar=False, normalize_embeddings=True
        )
        self.ledger.record(None, elapsed=time.perf_counter() - started, cached=False)
        return [[float(x) for x in row] for row in vectors]


class OpenRouterEmbedder:
    """Embeddings distants `openai/text-embedding-3-small` (1536 dim), coût mesuré."""

    dim = 1536

    def __init__(self, client: OpenRouterClient | None = None, *, model: str = DEFAULT_EMBED_MODEL) -> None:
        self._client = client or OpenRouterClient(ledger=CostLedger(label="embed"))
        self._model = model
        self.name = f"openrouter:{model.split('/')[-1]}"

    @property
    def ledger(self) -> CostLedger:
        return self._client.ledger

    def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        return self._client.embed(list(texts), model=self._model).vectors


class EmbeddingScorer:
    """Embeddings (locaux ou distants) puis régression logistique.

    Les vecteurs sont calculés une fois par texte et mémorisés : en validation croisée le
    même énoncé est vu cinq fois. Ce cache est la raison pour laquelle le banc d'ablation
    mesure le temps d'inférence séparément du temps d'entraînement.
    """

    def __init__(self, embedder: Any, *, C: float = 1.0) -> None:
        self._embedder = embedder
        self._C = C
        self.name = f"{getattr(embedder, 'name', 'embed')}+logreg"
        self.threshold = DEFAULT_THRESHOLD
        self._model: Any = None
        self._cache: dict[str, list[float]] = {}

    @property
    def ledger(self) -> CostLedger:
        return getattr(self._embedder, "ledger", CostLedger(label="embed"))

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        missing = [t for t in dict.fromkeys(texts) if t not in self._cache]
        if missing:
            for text, vector in zip(missing, self._embedder(missing)):
                self._cache[text] = vector
        return [self._cache[t] for t in texts]

    def fit(self, texts: Sequence[str], labels: Sequence[int]) -> "EmbeddingScorer":
        from sklearn.linear_model import LogisticRegression

        self._model = LogisticRegression(
            C=self._C, class_weight="balanced", max_iter=5000, random_state=0
        )
        self._model.fit(self.embed(texts), list(labels))
        return self

    def score(self, texts: Sequence[str]) -> list[float]:
        if self._model is None:
            raise RuntimeError("EmbeddingScorer.fit doit être appelé avant score")
        return [float(p) for p in self._model.predict_proba(self.embed(texts))[:, 1]]


# Tous les exemples de cette rubrique sont FABRIQUÉS. La première version de `_RUBRIC`
# illustrait ses critères avec quatre énoncés du jeu d'évaluation recopiés mot pour mot,
# tous étiquetés positifs (GitHub--5, Coursera--0, Huggingface--23, Apple--11), et ses
# contre-exemples négatifs décrivaient un à un les sites du corpus qui ne portent aucun
# positif (Cambridge Dictionary, ArXiv, ESPN, Wolfram Alpha). Le juge ne voyait donc pas ces
# cas, il les relisait dans son propre prompt : la comparaison avec les classifieurs, qui
# n'apprennent que sur 111 exemples par pli, était structurellement déloyale, et
# l'enseignement qualitatif qu'on en tirait une tautologie. Diagnostic posé par la
# vérification adverse du 16/08/2026 (problème B1).
#
# Règles appliquées à la réécriture, à vérifier avant toute modification de ce texte :
#   1. aucun exemple ne provient d'un benchmark existant, ni d'aucun corpus évalué ;
#   2. aucun exemple n'emprunte le domaine de l'un des quinze sites de WebVoyager ;
#   3. les domaines retenus sont volontairement étrangers au corpus (halage et mouillage
#      fluvial, camping, dépôt d'autocars, artisanat, archives d'un club), afin qu'aucune
#      formulation notée ne puisse être reconnue, même par paraphrase ;
#   4. chaque mot de contenu est soit absent des 643 énoncés de WebVoyager, soit assez
#      fréquent (≥ 5 énoncés) pour relever de l'anglais courant. Le régime intermédiaire,
#      un mot rare partagé avec quelques énoncés notés, est celui d'une fuite par
#      paraphrase, et il est interdit ;
#   5. les définitions et les règles de décision restent celles de la grille d'annotation :
#      la réécriture retire les énoncés du corpus, pas la grille.
#
# Les points 1 à 4 sont vérifiés par `experiments/check_rubric_leak.py`, qui échoue sur
# l'ancienne rubrique et passe sur celle-ci. À relancer après toute retouche de ce texte.
#
# Ce que le juge reçoit encore, et qui reste une limite assumée du protocole (mesurée par la
# ligne « prompt plain » de `experiments/ABLATION_L3.md`), c'est la définition de
# l'étiquette, identique à celle de l'annotateur. Ce qu'il ne reçoit plus, ce sont les
# énoncés qu'on lui demande ensuite de noter.
_RUBRIC = """A web-agent benchmark task is AMBIGUOUS when, reading the statement alone, two
different answers can both be equally correct because the statement gives no
tie-breaking criterion and the website imposes no deterministic order.

Consider ambiguous:
- several items satisfy the stated filters and nothing selects one of them
  ("a canal mooring with a standpipe, free on a Sunday", "a campsite pitch for a tent
  and an awning");
- the selection criterion is subjective or is not a property the site exposes
  ("a rewarding towpath loop", "a trustworthy locksmith", "an inspiring pottery exhibit");
- the referent or the category is not determined ("the depot's entry-level maintenance
  tier" when three tiers are sold alongside each other; a subscribers-only archive the
  site does not have);
- the expected output is not determined: pick k items among many equivalent ones, or
  free generation with no reference answer ("a few lines of free prose about the
  towpath").

Consider NOT ambiguous:
- a deterministic order given by the statement or by the site decides the answer, or its
  prefix when the statement is plural (the lowest joining fee, the first coach of the
  morning, the most recent entry in the register, a named section of the site);
- a named, unique object (an object designated by its catalogue reference, a form
  identified by its number, a stop named in the statement);
- the answer varies only in FORM, not in TARGET (restating the opening hours of one
  named branch);
- a task that is impossible, outdated or blocked is NOT ambiguous for that reason —
  judge only whether several answers would be equally correct."""

#: Deux formulations de prompt, pour isoler ce que le juge doit à la rubrique. ``plain``
#: mesure le juge tel qu'on l'utiliserait sans y réfléchir ; ``rubric`` lui transmet la même
#: définition que celle de l'annotateur. C'est la seule approche qui reçoit la grille
#: d'étiquetage, et l'écart entre les deux est mesuré dans l'ablation.
JUDGE_PROMPTS: dict[str, str] = {
    "plain": (
        "You rate web-agent benchmark tasks.\n"
        "Rate how AMBIGUOUS the task statement below is, from 0.0 (perfectly "
        "unambiguous: exactly one answer is correct) to 1.0 (highly ambiguous: many "
        "different answers would be equally correct).\n"
        'Answer with strict JSON only: {"score": <float 0-1>, "reason": "<12 words max>"}'
    ),
    "rubric": (
        "You rate web-agent benchmark tasks against the rubric below.\n\n"
        + _RUBRIC
        + "\n\nRate the task statement from 0.0 (clearly not ambiguous) to 1.0 (clearly "
        "ambiguous).\n"
        'Answer with strict JSON only: {"score": <float 0-1>, "reason": "<12 words max>"}'
    ),
}

_JSON_RE = re.compile(r"\{.*?\}", re.S)
_FLOAT_RE = re.compile(r"[01](?:\.\d+)?")


def parse_judge_reply(text: str) -> tuple[float | None, str]:
    """Extrait ``(score, motif)`` d'une réponse de juge, tolérante aux enrobages."""
    match = _JSON_RE.search(text or "")
    if match:
        try:
            payload = json.loads(match.group(0))
            score = payload.get("score")
            if score is not None:
                return max(0.0, min(1.0, float(score))), str(payload.get("reason", ""))[:200]
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    fallback = _FLOAT_RE.search(text or "")
    if fallback:
        return max(0.0, min(1.0, float(fallback.group(0)))), "(score extrait sans JSON)"
    return None, "(réponse illisible)"


class LlmJudgeScorer:
    """Juge LLM : une note d'ambiguïté de 0 à 1 par énoncé, seuil calibré.

    Le juge n'est pas entraîné : ``fit`` ne sert qu'à calibrer le seuil de décision sur
    les plis d'entraînement, exactement comme un praticien le ferait sur un lot annoté.
    Les notes sont mises en cache par le client, si bien qu'une validation croisée à
    cinq plis n'appelle l'API qu'une fois par énoncé.
    """

    def __init__(
        self,
        client: OpenRouterClient | None = None,
        *,
        model: str = DEFAULT_CHAT_MODEL,
        prompt: str = "rubric",
        system: str | None = None,
        variant: str | None = None,
        temperature: float = 0.0,
        max_workers: int = 8,
    ) -> None:
        self._client = client or OpenRouterClient(ledger=CostLedger(label="judge"))
        self._model = model
        self._prompt_key = prompt
        # ``system`` court-circuite ``JUDGE_PROMPTS`` : c'est ce qui permet à un banc
        # d'ablation de rejouer une rubrique *antérieure* (par exemple celle, fuitée, du
        # 15/08/2026) sans la réintroduire dans le code de l'outil. Toute autre valeur
        # que celles de ``JUDGE_PROMPTS`` doit rester cantonnée aux expériences.
        self._system = JUDGE_PROMPTS[prompt] if system is None else system
        self._variant = variant
        self._temperature = temperature
        self._max_workers = max_workers
        self.name = f"llm-judge:{model.split('/')[-1]}:{prompt}"
        self.threshold = DEFAULT_THRESHOLD
        self._cache: dict[str, float] = {}
        self.reasons: dict[str, str] = {}
        self.unparsed = 0

    @property
    def ledger(self) -> CostLedger:
        return self._client.ledger

    def _score_one(self, text: str) -> tuple[str, float, str]:
        result = self._client.chat(
            [
                {"role": "system", "content": self._system},
                {"role": "user", "content": f"Task statement:\n{text}"},
            ],
            model=self._model,
            temperature=self._temperature,
            max_tokens=120,
            variant=self._variant,
        )
        score, reason = parse_judge_reply(result.text)
        if score is None:
            self.unparsed += 1
            score = 0.5  # abstention : note neutre, consignée
        return text, score, reason

    def score(self, texts: Sequence[str]) -> list[float]:
        missing = [t for t in dict.fromkeys(texts) if t not in self._cache]
        if missing:
            if self._max_workers > 1 and len(missing) > 1:
                from concurrent.futures import ThreadPoolExecutor

                with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
                    for text, score, reason in pool.map(self._score_one, missing):
                        self._cache[text] = score
                        self.reasons[text] = reason
            else:
                for text in missing:
                    _, score, reason = self._score_one(text)
                    self._cache[text] = score
                    self.reasons[text] = reason
        return [self._cache[t] for t in texts]

    def fit(self, texts: Sequence[str], labels: Sequence[int]) -> "LlmJudgeScorer":
        self.threshold = calibrate_threshold(self.score(texts), labels)
        return self


def build_scorer(
    backend: str | None = None,
    *,
    client: OpenRouterClient | None = None,
    annotations: AnnotatedSet | None = None,
    fit: bool = True,
    **kwargs: Any,
) -> AmbiguityScorer:
    """Instancie l'approche demandée et, par défaut, l'entraîne sur le jeu annoté.

    ``backend`` vaut ``tfidf``, ``minilm``, ``openrouter`` ou ``llm`` ; à défaut, la variable
    d'environnement ``BDOCTOR_L3_BACKEND``. ``client`` permet de mutualiser cache et
    comptabilité entre backends distants, et ``fit=False`` rend un scorer non entraîné (donc,
    pour le juge, non calibré).
    """
    name = (backend or DEFAULT_BACKEND).strip().lower()
    if name in ("tfidf", "tf-idf", "lexical"):
        scorer: Any = TfidfScorer(**kwargs)
    elif name in ("minilm", "local", "sentence-transformers"):
        scorer = EmbeddingScorer(MiniLmEmbedder(), **kwargs)
    elif name in ("openrouter", "openai-embed", "embed"):
        scorer = EmbeddingScorer(OpenRouterEmbedder(client), **kwargs)
    elif name in ("llm", "judge", "llm-judge"):
        scorer = LlmJudgeScorer(client, **kwargs)
    else:
        raise ValueError(
            f"backend L3 inconnu : {name!r} (attendu : tfidf, minilm, openrouter, llm)"
        )
    if fit:
        data = annotations or load_annotations()
        scorer.fit(data.texts, data.labels)
        _guard_degenerate_threshold(scorer, data)
    return scorer


def _guard_degenerate_threshold(scorer: Any, data: AnnotatedSet, *, ceiling: float = 0.9) -> None:
    """Refuse un seuil qui signale (presque) tout le corpus, et le ramène à 0,5.

    La maximisation du F1 peut choisir un seuil dégénéré quand les notes ne séparent pas les
    classes : c'est le cas du juge `gemini-2.5-flash-lite`, dont 78 % des notes valent 0,0,
    si bien que le seuil optimal devient 0,0 et que le détecteur déclare tout le monde
    ambigu. Inacceptable en exploitation, mais à publier tel quel en ablation : le garde-fou
    est donc ici, dans la fabrique de l'outil, et non dans `calibrate_threshold`, qui reste
    l'estimateur brut utilisé par le banc.
    """
    flagged = sum(1 for s in scorer.score(data.texts) if s >= scorer.threshold)
    if flagged > ceiling * len(data):
        scorer.threshold = DEFAULT_THRESHOLD
        scorer.calibration_degenerate = True


_DEFAULT_SCORER: AmbiguityScorer | None = None


def _default_scorer() -> AmbiguityScorer:
    global _DEFAULT_SCORER
    if _DEFAULT_SCORER is None:
        _DEFAULT_SCORER = build_scorer()
    return _DEFAULT_SCORER


def detect_ambiguity(
    task: Task,
    *,
    today: _dt.date | None = None,
    scorer: AmbiguityScorer | None = None,
) -> list[Finding]:
    """Émet un constat T5 si l'énoncé est jugé ambigu par le backend configuré.

    Le constat est plafonné à ``Severity.MEDIUM`` : une tâche ambiguë s'exécute, c'est son
    verdict qui est arbitraire. Le canal est ``LLM`` pour le juge et les embeddings distants,
    ``STATIC`` pour les backends hors ligne, parce qu'un rapport doit dire d'où vient ce
    qu'il affirme.
    """
    engine = scorer or _default_scorer()
    return run_ambiguity([task], scorer=engine, today=today)[0]


def run_ambiguity(
    tasks: Sequence[Task],
    *,
    scorer: AmbiguityScorer | None = None,
    today: _dt.date | None = None,
) -> list[list[Finding]]:
    """Version par lots : un appel réseau pour tout le corpus (embeddings, juge).

    Renvoie une liste de constats par tâche, dans l'ordre d'entrée.
    """
    engine = scorer or _default_scorer()
    day = today or _dt.date.today()
    scores = engine.score([t.question for t in tasks])
    channel = Channel.LLM if _is_remote(engine) else Channel.STATIC
    out: list[list[Finding]] = []
    for task, score in zip(tasks, scores):
        if score < engine.threshold:
            out.append([])
            continue
        out.append(
            [
                Finding(
                    category=Category.AMBIGUITY,
                    severity=Severity.MEDIUM,
                    confidence=round(float(score), 3),
                    evidence=task.question[:200],
                    detector=DETECTOR_NAME,
                    channel=channel,
                    task_id=task.task_id,
                    signal=f"ambiguity:{getattr(engine, 'name', 'unknown')}",
                    details={
                        "score": round(float(score), 3),
                        "threshold": round(float(engine.threshold), 3),
                        "backend": getattr(engine, "name", "unknown"),
                        "reason": getattr(engine, "reasons", {}).get(task.question, ""),
                        "rationale": (
                            "plusieurs réponses peuvent satisfaire l'énoncé : le verdict du "
                            "juge dépend de celle que l'agent rapporte"
                        ),
                    },
                    observed_at=day,
                )
            ]
        )
    return out


def _is_remote(scorer: Any) -> bool:
    name = getattr(scorer, "name", "")
    return name.startswith("llm-judge") or "openrouter" in name


detect_ambiguity.name = DETECTOR_NAME  # type: ignore[attr-defined]
