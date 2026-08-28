"""L3 — accès aux modèles distants (OpenRouter) : clé, cache, et comptabilité du coût.

Unique point de contact du projet avec une API payante. Trois contraintes :

1. La clé n'est jamais dans le code ni dans le dépôt : elle est lue dans
   ``OPENROUTER_API_KEY`` et, à défaut, dans un ``.env`` non versionné remonté depuis le
   répertoire courant. Elle n'apparaît ni dans les journaux, ni dans le cache, ni dans
   les messages d'erreur.

2. Le coût consigné est celui facturé (``usage.cost``, en dollars), jamais une estimation
   à partir d'une grille tarifaire.

3. Tout appel est mis en cache sur disque, indexé par le hachage de la requête complète
   (modèle + charge utile) : une ré-exécution est gratuite et ne dépend plus de la
   disponibilité du fournisseur.

Le client est utilisable depuis plusieurs fils d'exécution (verrou sur le cache), ce dont
l'ablation se sert pour paralléliser les appels de juge.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

__all__ = [
    "CostLedger",
    "ChatResult",
    "EmbeddingResult",
    "OpenRouterClient",
    "OpenRouterError",
    "load_api_key",
    "DEFAULT_CHAT_MODEL",
    "CHEAP_CHAT_MODEL",
    "DEFAULT_EMBED_MODEL",
]

#: Modèle de conversation par défaut : ce n'est pas le moins cher, c'est un résultat de
#: mesure. Campagne à rubrique propre du 16/08/2026 (`experiments/ablation_l3_clean.py`,
#: rapport `experiments/ABLATION_L3.md`), qui remplace celle du 15/08 : `gemini-2.5-flash`
#: obtient F1 0,715 ± 0,006 et AUC 0,772 ; `gemini-2.5-flash-lite` tombe à F1 0,245 et
#: AUC 0,551, soit presque le hasard. Deux réserves : le F1 de 0,827 annoncé le 15/08 était
#: gonflé par cinq énoncés du jeu évalué recopiés dans la rubrique du juge, et l'avantage
#: du juge propre sur la ligne de base gratuite n'est pas significatif à 5 % sur 139 items
#: (ce qu'il apporte est de la précision, 0,89 contre 0,66, à rappel égal).
DEFAULT_CHAT_MODEL = os.environ.get("BDOCTOR_L3_CHAT_MODEL", "google/gemini-2.5-flash")

#: Le modèle le moins cher du fournisseur, conservé comme point de comparaison de
#: l'ablation et pour les usages où le volume prime sur la qualité du jugement.
CHEAP_CHAT_MODEL = "google/gemini-2.5-flash-lite"

#: Modèle d'embedding par défaut (1536 dimensions).
DEFAULT_EMBED_MODEL = "openai/text-embedding-3-small"

_BASE_URL = "https://openrouter.ai/api/v1"

#: Clé sous laquelle la latence de l'appel est consignée dans l'entrée de cache.
_LATENCY_KEY = "__bdoctor_latency_s"


class OpenRouterError(RuntimeError):
    """Erreur d'appel à l'API, après épuisement des reprises."""


def load_api_key(env_var: str = "OPENROUTER_API_KEY", *, start: Path | None = None) -> str:
    """Retourne la clé d'API, depuis l'environnement ou un ``.env`` non versionné.

    La recherche remonte les répertoires parents depuis ``start`` (par défaut le
    répertoire courant) jusqu'à trouver un fichier ``.env`` contenant la variable.
    Aucune valeur n'est journalisée : en cas d'échec, le message d'erreur ne cite que
    le nom de la variable attendue.
    """
    value = os.environ.get(env_var)
    if value:
        return value.strip()

    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / ".env"
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, raw = line.partition("=")
            if name.strip() == env_var:
                return raw.strip().strip("'\"")
    raise OpenRouterError(
        f"{env_var} introuvable : exportez la variable ou placez-la dans un fichier .env "
        "non versionné à la racine du projet."
    )


@dataclass(slots=True)
class CostLedger:
    """Comptabilité d'une campagne d'appels : volume, jetons, coût réel, temps.

    Les appels servis par le cache sont comptés à part et à coût nul : le coût d'une
    première mesure et celui d'une ré-exécution ne sont pas le même chiffre.
    """

    label: str = ""
    calls: int = 0
    cached_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    #: Coût qui aurait été facturé sans le cache, relu dans la réponse mémorisée : c'est
    #: lui qui doit figurer dans un tableau coût/performance.
    avoided_cost_usd: float = 0.0
    #: Temps de modèle évité par le cache, relu lui aussi dans la réponse mémorisée : sans
    #: lui, une ré-exécution afficherait « 0,1 s » pour un juge qui met 0,2 s par tâche.
    avoided_time_s: float = 0.0
    wall_time_s: float = 0.0
    errors: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def record(
        self,
        usage: Mapping[str, Any] | None,
        *,
        elapsed: float,
        cached: bool,
        avoided_elapsed: float = 0.0,
    ) -> None:
        with self._lock:
            self.wall_time_s += elapsed
            if cached:
                self.cached_calls += 1
                self.avoided_time_s += avoided_elapsed
                if usage:
                    self.avoided_cost_usd += float(usage.get("cost") or 0.0)
                return
            self.calls += 1
            if usage:
                self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
                self.completion_tokens += int(usage.get("completion_tokens") or 0)
                self.cost_usd += float(usage.get("cost") or 0.0)

    @property
    def first_run_cost_usd(self) -> float:
        """Coût de la première mesure : ce qui a été payé, plus ce que le cache a évité."""
        return self.cost_usd + self.avoided_cost_usd

    @property
    def model_time_s(self) -> float:
        """Temps de modèle cumulé, appels servis par le cache compris.

        Indépendant du nombre de fils d'exécution, donc comparable entre machines, là où
        le temps de paroi ne dit que le parallélisme choisi ce jour-là.
        """
        return self.wall_time_s + self.avoided_time_s

    def record_error(self) -> None:
        with self._lock:
            self.errors += 1

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict[str, Any]:
        # Sérialisation explicite : `asdict` échouerait sur le verrou de synchronisation.
        return {
            "label": self.label,
            "calls": self.calls,
            "cached_calls": self.cached_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "avoided_cost_usd": round(self.avoided_cost_usd, 6),
            "first_run_cost_usd": round(self.first_run_cost_usd, 6),
            "wall_time_s": round(self.wall_time_s, 3),
            "avoided_time_s": round(self.avoided_time_s, 3),
            "model_time_s": round(self.model_time_s, 3),
            "errors": self.errors,
        }

    def merge(self, other: "CostLedger") -> "CostLedger":
        """Somme de deux comptabilités (p. ex. embeddings + juge)."""
        merged = CostLedger(label=f"{self.label}+{other.label}".strip("+"))
        merged.calls = self.calls + other.calls
        merged.cached_calls = self.cached_calls + other.cached_calls
        merged.prompt_tokens = self.prompt_tokens + other.prompt_tokens
        merged.completion_tokens = self.completion_tokens + other.completion_tokens
        merged.cost_usd = self.cost_usd + other.cost_usd
        merged.avoided_cost_usd = self.avoided_cost_usd + other.avoided_cost_usd
        merged.avoided_time_s = self.avoided_time_s + other.avoided_time_s
        merged.wall_time_s = self.wall_time_s + other.wall_time_s
        merged.errors = self.errors + other.errors
        return merged


@dataclass(frozen=True, slots=True)
class ChatResult:
    """Réponse d'un appel de conversation."""

    text: str
    model: str
    cost_usd: float
    cached: bool
    usage: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """Vecteurs d'un appel d'embedding (un vecteur par texte, dans l'ordre d'entrée)."""

    vectors: list[list[float]]
    model: str
    cost_usd: float
    cached: bool
    usage: Mapping[str, Any] = field(default_factory=dict)


class OpenRouterClient:
    """Client minimal OpenRouter : conversation, embeddings, cache disque, comptabilité.

    Args:
        api_key: clé d'API ; lue dans l'environnement ou un ``.env`` si omise.
        cache_dir: répertoire du cache ; ``None`` désactive le cache. Par défaut,
            ``$BDOCTOR_L3_CACHE`` ou ``runs/l3_cache`` sous la racine du projet.
        timeout: délai maximal d'un appel, en secondes.
        max_retries: nombre de reprises sur 429 / 5xx, avec attente exponentielle.
        ledger: comptabilité à alimenter (une est créée si omise).
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        cache_dir: str | Path | None = "auto",
        timeout: float = 90.0,
        max_retries: int = 4,
        ledger: CostLedger | None = None,
        base_url: str = _BASE_URL,
    ) -> None:
        self._api_key = api_key or load_api_key()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self.ledger = ledger or CostLedger(label="openrouter")
        self._cache_dir = self._resolve_cache_dir(cache_dir)
        self._cache_lock = threading.Lock()
        self._client: Any = None

    # -- infrastructure

    @staticmethod
    def _resolve_cache_dir(cache_dir: str | Path | None) -> Path | None:
        if cache_dir is None:
            return None
        if cache_dir == "auto":
            env = os.environ.get("BDOCTOR_L3_CACHE")
            if env:
                path = Path(env)
            else:
                # racine du projet = parent de benchmark_doctor/
                path = Path(__file__).resolve().parents[2] / "runs" / "l3_cache"
        else:
            path = Path(cache_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _http(self) -> Any:
        if self._client is None:
            try:
                import httpx  # import paresseux : la couche L1 ne dépend de rien
            except ModuleNotFoundError as exc:  # pragma: no cover - dépendance optionnelle
                raise OpenRouterError(
                    "httpx est requis pour la couche L3 : pip install -e '.[llm]'"
                ) from exc
            self._client = httpx.Client(
                timeout=self._timeout,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    # Identification de l'appelant demandée par OpenRouter.
                    "X-Title": "benchmark-doctor",
                },
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "OpenRouterClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- cache

    @staticmethod
    def _cache_key(endpoint: str, payload: Mapping[str, Any]) -> str:
        blob = json.dumps({"endpoint": endpoint, "payload": payload}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path | None:
        if self._cache_dir is None:
            return None
        # Deux niveaux pour éviter des répertoires de dizaines de milliers d'entrées.
        sub = self._cache_dir / key[:2]
        sub.mkdir(parents=True, exist_ok=True)
        return sub / f"{key}.json"

    def _cache_read(self, key: str) -> dict[str, Any] | None:
        path = self._cache_path(key)
        if path is None or not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):  # cache corrompu : on refait l'appel
            return None

    def _cache_write(self, key: str, response: Mapping[str, Any]) -> None:
        path = self._cache_path(key)
        if path is None:
            return
        with self._cache_lock:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)

    # -- appels

    def _post(self, endpoint: str, payload: Mapping[str, Any], *, use_cache: bool) -> tuple[dict[str, Any], bool, float]:
        key = self._cache_key(endpoint, payload)
        started = time.perf_counter()
        if use_cache:
            hit = self._cache_read(key)
            if hit is not None:
                return hit, True, time.perf_counter() - started

        url = f"{self._base_url}{endpoint}"
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._http().post(url, json=dict(payload))
                if response.status_code in (429, 500, 502, 503, 504):
                    raise OpenRouterError(f"HTTP {response.status_code}")
                response.raise_for_status()
                data = response.json()
                if "error" in data and not data.get("choices") and not data.get("data"):
                    raise OpenRouterError(str(data["error"])[:300])
                elapsed = time.perf_counter() - started
                # Latence écrite dans l'entrée de cache : une ré-exécution republie le
                # temps de la mesure d'origine, pas celui d'une lecture de fichier.
                data[_LATENCY_KEY] = round(elapsed, 4)
                if use_cache:
                    self._cache_write(key, data)
                return data, False, elapsed
            except Exception as exc:  # noqa: BLE001 - on reprend sur toute erreur transitoire
                last_error = exc
                self.ledger.record_error()
                if attempt >= self._max_retries:
                    break
                time.sleep(min(2.0**attempt, 16.0))
        raise OpenRouterError(f"échec de l'appel {endpoint} après {self._max_retries + 1} tentatives : {last_error}")

    def chat(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        model: str = DEFAULT_CHAT_MODEL,
        temperature: float = 0.0,
        max_tokens: int = 400,
        seed: int | None = None,
        variant: str | None = None,
        use_cache: bool = True,
    ) -> ChatResult:
        """Un appel de conversation, coût réel consigné dans le registre.

        Args:
            variant: étiquette libre incluse dans la clé de cache. Sert à obtenir
                plusieurs tirages indépendants d'un même prompt (mesure de la variance
                du juge) sans que le cache ne renvoie trois fois la même réponse.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": [dict(m) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "usage": {"include": True},
        }
        if seed is not None:
            payload["seed"] = seed
        # `variant` n'est jamais transmis au fournisseur : il ne sert qu'à séparer les
        # tirages dans le cache.
        cache_payload = dict(payload)
        if variant is not None:
            cache_payload["__variant"] = variant

        endpoint = "/chat/completions"
        cache_key = self._cache_key(endpoint, cache_payload)
        started = time.perf_counter()
        cached_response = self._cache_read(cache_key) if use_cache else None
        if cached_response is not None:
            elapsed = time.perf_counter() - started
            self.ledger.record(
                cached_response.get("usage"),
                elapsed=elapsed,
                cached=True,
                avoided_elapsed=float(cached_response.get(_LATENCY_KEY) or 0.0),
            )
            return ChatResult(
                text=_first_message(cached_response),
                model=model,
                cost_usd=0.0,
                cached=True,
                usage=cached_response.get("usage") or {},
            )

        data, _, elapsed = self._post(endpoint, payload, use_cache=False)
        if use_cache:
            self._cache_write(cache_key, data)
        usage = data.get("usage") or {}
        self.ledger.record(usage, elapsed=elapsed, cached=False)
        return ChatResult(
            text=_first_message(data),
            model=model,
            cost_usd=float(usage.get("cost") or 0.0),
            cached=False,
            usage=usage,
        )

    def embed(
        self,
        texts: Sequence[str],
        *,
        model: str = DEFAULT_EMBED_MODEL,
        batch_size: int = 64,
        use_cache: bool = True,
    ) -> EmbeddingResult:
        """Vectorise une liste de textes (par lots), coût réel consigné."""
        vectors: list[list[float]] = []
        total_cost = 0.0
        all_cached = True
        usage_sum: dict[str, Any] = {"prompt_tokens": 0, "total_tokens": 0}
        for start in range(0, len(texts), batch_size):
            chunk = list(texts[start : start + batch_size])
            payload = {"model": model, "input": chunk}
            data, cached, elapsed = self._post("/embeddings", payload, use_cache=use_cache)
            usage = data.get("usage") or {}
            self.ledger.record(
                usage,
                elapsed=elapsed,
                cached=cached,
                avoided_elapsed=float(data.get(_LATENCY_KEY) or 0.0) if cached else 0.0,
            )
            all_cached = all_cached and cached
            if not cached:
                total_cost += float(usage.get("cost") or 0.0)
                usage_sum["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
                usage_sum["total_tokens"] += int(usage.get("total_tokens") or 0)
            ordered = sorted(data["data"], key=lambda d: d.get("index", 0))
            vectors.extend([list(map(float, d["embedding"])) for d in ordered])
        if len(vectors) != len(texts):
            raise OpenRouterError(f"{len(vectors)} vecteurs pour {len(texts)} textes")
        return EmbeddingResult(vectors=vectors, model=model, cost_usd=total_cost, cached=all_cached, usage=usage_sum)


def _first_message(data: Mapping[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return (message.get("content") or "").strip()
