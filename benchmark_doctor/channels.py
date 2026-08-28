"""Canaux d'accès au web vivant : la couche transport des sondes L2.

Le 15/08/2026 à 23 h 10 UTC, ``https://www.allrecipes.com/`` a renvoyé 402 Payment
Required (en-tête ``__cf_bm``, ``server: cloudflare``, le pay-per-crawl de Cloudflare)
depuis une IP de datacenter, et 200 OK depuis un navigateur cloud quarante-sept secondes
plus tard. Même URL, même minute, deux verdicts opposés.

D'où la contrainte de méthode qui structure ce module : le statut d'une tâche de
benchmark n'est pas une propriété de la tâche, mais du couple (tâche, canal d'accès).
Publier « Allrecipes est mort » sans dire depuis où l'on a regardé revient à compter comme
mortes des tâches simplement invisibles depuis l'infrastructure de mesure. Une
`Observation` porte donc toujours son canal, son heure et ses en-têtes discriminants.

Reste le canal de l'infrastructure de mesure elle-même : la campagne du 15/08 est sortie
par un proxy d'entreprise qui filtre certains hôtes et répond alors 400/403 à la place du
site. `Observation.looks_proxy_mediated` repère ces réponses pour que le classifieur L2
les impute au canal et non au site.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from .models import Channel

__all__ = [
    "Observation",
    "ChannelError",
    "ChannelUnavailable",
    "BaseChannel",
    "DirectHTTPChannel",
    "BrowserChannel",
    "PlaywrightChannel",
    "RecordedChannel",
    "BROWSER_HEADERS",
    "MINIMAL_HEADERS",
    "PROXY_BODY_MARKERS",
    "DISCRIMINATING_HEADERS",
]

#: En-têtes conservés dans chaque observation. La liste est volontairement courte et
#: fermée : ce sont ceux qui portent l'information de blocage (fournisseur anti-bot,
#: action du WAF, cookie de challenge), pas ceux qui identifient l'utilisateur.
DISCRIMINATING_HEADERS: tuple[str, ...] = (
    "server",
    "content-type",
    "content-length",
    "location",
    "retry-after",
    "cf-ray",
    "cf-mitigated",
    "cf-cache-status",
    "x-amzn-waf-action",
    "x-amz-cf-pop",
    "x-cache",
    "x-datadome",
    "x-iinfo",
    "x-akamai-transformed",
    "x-kpsdk-ct",
    "set-cookie",
    "via",
)

#: Profil « navigateur » : un Chrome de bureau récent, en-têtes complets et cohérents.
#: `Accept-Encoding` omet volontairement ``br`` : sans décodeur Brotli installé, le corps
#: reviendrait binaire et le classifieur de signatures lirait du bruit. Un paramètre de
#: mesure ne doit jamais dépendre d'un paquet optionnel présent par hasard.
BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

#: Profil « client nu » : ce qu'envoie un script de CI qui n'a rien configuré. Comparer
#: les deux profils mesure la part du verdict imputable à la seule présentation du client,
#: à IP et à instant constants.
MINIMAL_HEADERS: dict[str, str] = {
    "User-Agent": "python-requests/2.x",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
}

#: Marqueurs d'une réponse fabriquée par l'infrastructure de mesure (proxy d'egress,
#: passerelle d'entreprise) et non par le site visé. Les imputer au site serait une
#: erreur de mesure : ce sont des faux positifs de decay.
PROXY_BODY_MARKERS: tuple[str, ...] = (
    "host not in allowlist",
    "add this host to your network egress settings",
    "request path could not be canonicalized",
    "access to this repository is not enabled for this session",
    "proxy authentication required",
    "blocked by your organization",
    "egress policy",
)


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


@dataclass(frozen=True, slots=True)
class Observation:
    """Le résultat d'un accès à une URL depuis un canal donné.

    Args:
        channel_name: nom de l'instance de canal, plus précis que le canal générique
            (p. ex. ``"direct_http:browser"`` vs ``"direct_http:minimal"``).
        status: code HTTP, ``None`` si la requête n'a jamais abouti.
        body_size: taille du corps décodé, en octets.
        headers: en-têtes retenus (cf. `DISCRIMINATING_HEADERS`), clés en minuscules.
        observed_at: instant de l'observation (UTC).
        meta: informations propres au canal (titre de page rendue, région du POP…).
    """

    url: str
    channel: Channel
    channel_name: str
    status: int | None = None
    final_url: str | None = None
    body_size: int = 0
    headers: Mapping[str, str] = field(default_factory=dict)
    excerpt: str = ""
    redirect_chain: Sequence[int] = field(default_factory=tuple)
    elapsed_ms: float | None = None
    error: str | None = None
    observed_at: _dt.datetime = field(default_factory=_now)
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "channel", Channel(self.channel))
        object.__setattr__(
            self, "headers", {k.lower(): v for k, v in dict(self.headers).items()}
        )
        object.__setattr__(self, "redirect_chain", tuple(self.redirect_chain))
        if isinstance(self.observed_at, str):
            object.__setattr__(
                self, "observed_at", _dt.datetime.fromisoformat(self.observed_at)
            )

    # -- lectures dérivées

    @property
    def reached(self) -> bool:
        """Vrai si une réponse HTTP a été obtenue (même une réponse de refus)."""
        return self.status is not None

    @property
    def ok(self) -> bool:
        """Vrai si le code est 2xx. Ne dit rien du contenu : un challenge anti-bot AWS
        WAF répond 202, et un soft-404 répond 200."""
        return self.status is not None and 200 <= self.status < 300

    @property
    def host(self) -> str:
        return urlsplit(self.url).netloc.lower()

    @property
    def path(self) -> str:
        return urlsplit(self.url).path or "/"

    @property
    def final_path(self) -> str:
        return urlsplit(self.final_url or self.url).path or "/"

    @property
    def redirect_absorption(self) -> str | None:
        """Type d'« absorption » de l'URL demandée par une URL plus haute du même site.

        Renvoie ``"root"`` si l'URL profonde a fini sur la racine, ``"ancestor"`` si elle
        a fini sur un de ses répertoires parents, ``None`` sinon. C'est la signature d'un
        contenu retiré sans 404. Le cas « ancestor » n'est pas anecdotique : un mot
        inexistant sur ``dictionary.cambridge.org/dictionary/english/<mot>`` renvoie 200
        après redirection vers ``/dictionary/english/``, motif répandu sur les sites à
        sections (dictionnaires, catalogues, documentations).
        """
        if not self.final_url:
            return None
        if urlsplit(self.final_url).netloc.lower() != self.host:
            return None
        asked, final = self.path.rstrip("/"), self.final_path.rstrip("/")
        if not asked or asked == final:
            return None
        if not final:
            return "root"
        if asked.startswith(final + "/"):
            return "ancestor"
        return None

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())

    @property
    def looks_proxy_mediated(self) -> bool:
        """Vrai si la réponse a visiblement été fabriquée par le canal, pas par le site.

        Sans cette distinction, un proxy d'entreprise qui bloque ``github.com`` ferait
        apparaître 41 tâches GitHub comme mortes.
        """
        blob = (self.excerpt or "").lower()
        if any(marker in blob for marker in PROXY_BODY_MARKERS):
            return True
        if self.error and any(
            m in self.error.lower() for m in ("proxyerror", "tunnel connection failed", "407")
        ):
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "channel": self.channel.value,
            "channel_name": self.channel_name,
            "status": self.status,
            "final_url": self.final_url,
            "body_size": self.body_size,
            "headers": dict(self.headers),
            "excerpt": self.excerpt,
            "redirect_chain": list(self.redirect_chain),
            "elapsed_ms": round(self.elapsed_ms, 1) if self.elapsed_ms is not None else None,
            "error": self.error,
            "observed_at": self.observed_at.isoformat(),
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Observation":
        data = dict(payload)
        return cls(**data)


class ChannelError(RuntimeError):
    """Erreur imputable au canal (et non au site)."""


class ChannelUnavailable(ChannelError):
    """Le canal n'est pas utilisable dans cet environnement.

    Levée plutôt qu'un échec silencieux : une campagne doit consigner « ce canal n'a pas
    pu être mesuré » comme un fait, pas laisser croire que le site est en cause.
    """


class BaseChannel(ABC):
    """Contrat commun à tous les canaux.

    1. ``fetch`` ne lève jamais pour une erreur réseau : il renvoie une `Observation`
       portant ``error``, une campagne de 600 sondes ne devant pas s'arrêter au premier
       DNS capricieux.
    2. ``available`` répond sans effet de bord coûteux, pour qu'une campagne puisse
       annoncer d'emblée quels canaux elle exécutera.
    3. ``describe`` renvoie la provenance de la mesure (type d'egress, présence d'un
       proxy, profil d'en-têtes), bloc recopié tel quel dans le rapport.
    """

    #: Canal générique, tel qu'il figure dans les constats.
    kind: Channel = Channel.HTTP_DATACENTER
    #: Nom de l'instance, discriminant entre deux réglages du même canal.
    name: str = "base"

    @abstractmethod
    def fetch(self, url: str, *, timeout: float | None = None) -> Observation:
        """Récupère une URL et renvoie l'observation correspondante."""

    def available(self) -> bool:
        """Vrai si le canal peut être exécuté ici."""
        return True

    def describe(self) -> dict[str, Any]:
        """Provenance de la mesure, à consigner dans le rapport."""
        return {"name": self.name, "kind": self.kind.value, "available": self.available()}

    def fetch_many(
        self, urls: Iterable[str], *, timeout: float | None = None
    ) -> list[Observation]:
        return [self.fetch(u, timeout=timeout) for u in urls]

    def __repr__(self) -> str:  # pragma: no cover - confort de débogage
        return f"<{type(self).__name__} {self.name} ({self.kind.value})>"


class DirectHTTPChannel(BaseChannel):
    """Accès HTTP direct, sans navigateur : le canal le moins cher et le plus filtré.

    Deux profils d'en-têtes sont fournis (``"browser"`` et ``"minimal"``). Les comparer
    isole une variable : à IP, instant et URL identiques, la seule présentation du client
    suffit-elle à changer le verdict ?

    Args:
        profile: ``"browser"`` (en-têtes de Chrome) ou ``"minimal"`` (client nu).
        kind: canal générique déclaré. Passer `Channel.HTTP_RESIDENTIAL` quand la mesure
            sort par un proxy résidentiel : la classe ne peut pas le deviner.
        max_body: nombre d'octets lus au plus (les pages d'accueil pèsent jusqu'à 800 ko).
        excerpt_chars: longueur de l'extrait conservé comme preuve. Trois mille caractères
            et non mille : le marqueur ``awsWafCookieDomainList`` de l'interstitiel
            Booking apparaît au-delà du 1 500ᵉ caractère du corps, et un extrait trop court
            transforme un challenge en « page normale ».
        retries: nombre de nouvelles tentatives en cas d'erreur réseau uniquement (DNS,
            TLS, socket, délai dépassé). Jamais de réessai sur un code HTTP : un 402 ou un
            403 est une donnée, une socket coupée est du bruit.
        min_interval: délai minimal entre deux requêtes vers le même hôte, en secondes.
            Sonder 45 tâches d'un même site en rafale déclenche l'anti-bot que l'on
            prétend mesurer.
        allow_redirects: suit les redirections (nécessaire pour détecter ``redirect_home``).
        session: session ``requests`` à réutiliser (injectable pour les tests).
    """

    def __init__(
        self,
        *,
        profile: str = "browser",
        kind: Channel = Channel.HTTP_DATACENTER,
        timeout: float = 25.0,
        max_body: int = 500_000,
        excerpt_chars: int = 3_000,
        min_interval: float = 1.0,
        retries: int = 1,
        allow_redirects: bool = True,
        session: Any | None = None,
    ) -> None:
        if profile not in ("browser", "minimal"):
            raise ValueError(f"profil inconnu : {profile!r}")
        self.profile = profile
        self.kind = kind
        self.name = f"direct_http:{profile}"
        self.timeout = timeout
        self.max_body = max_body
        self.excerpt_chars = excerpt_chars
        self.min_interval = min_interval
        self.retries = max(0, int(retries))
        self.allow_redirects = allow_redirects
        self.headers = dict(BROWSER_HEADERS if profile == "browser" else MINIMAL_HEADERS)
        self._session = session
        self._last_hit: dict[str, float] = {}

    # -- infrastructure

    def _get_session(self) -> Any:
        if self._session is None:
            try:
                import requests  # import différé : L1 doit rester utilisable sans réseau
            except ImportError as exc:  # pragma: no cover - dépend de l'environnement
                raise ChannelUnavailable("le paquet `requests` est absent") from exc
            self._session = requests.Session()
        return self._session

    def available(self) -> bool:
        try:
            import requests  # noqa: F401
        except ImportError:  # pragma: no cover
            return False
        return True

    def _throttle(self, host: str) -> None:
        last = self._last_hit.get(host)
        if last is not None:
            wait = self.min_interval - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_hit[host] = time.monotonic()

    def describe(self) -> dict[str, Any]:
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        return {
            "name": self.name,
            "kind": self.kind.value,
            "available": self.available(),
            "profile": self.profile,
            "user_agent": self.headers.get("User-Agent"),
            "accept_encoding": self.headers.get("Accept-Encoding"),
            "timeout_s": self.timeout,
            "min_interval_s": self.min_interval,
            "network_retries": self.retries,
            "follows_redirects": self.allow_redirects,
            # Provenance honnête : la campagne du 15/08 est sortie par un proxy
            # interceptant, ce qui est en soi une caractéristique du canal.
            "egress_proxy": bool(proxy),
            "note": (
                "Brotli désactivé (Accept-Encoding sans `br`) : sans décodeur installé, "
                "le corps reviendrait binaire et fausserait la classification."
            ),
        }

    # -- accès

    def fetch(self, url: str, *, timeout: float | None = None) -> Observation:
        """Récupère une URL. Ne lève pas : une erreur réseau est une observation.

        Une erreur *réseau* (aucune réponse HTTP) est réessayée ``retries`` fois ; un code
        HTTP, quel qu'il soit, est renvoyé tel quel dès la première tentative.
        """
        observation = self._fetch_once(url, timeout=timeout)
        attempts = 1
        while not observation.reached and attempts <= self.retries:
            time.sleep(self.min_interval)
            observation = self._fetch_once(url, timeout=timeout)
            attempts += 1
        if attempts > 1:
            observation = Observation(
                **{**observation.to_dict(), "meta": {**observation.meta, "attempts": attempts}}
            )
        return observation

    def _fetch_once(self, url: str, *, timeout: float | None = None) -> Observation:
        started = time.monotonic()
        host = urlsplit(url).netloc.lower()
        self._throttle(host)
        try:
            session = self._get_session()
            response = session.get(
                url,
                headers=self.headers,
                timeout=timeout or self.timeout,
                allow_redirects=self.allow_redirects,
                stream=True,
            )
            raw = response.raw.read(self.max_body, decode_content=True) or b""
            body = raw.decode(response.encoding or "utf-8", errors="replace")
            declared = response.headers.get("Content-Length")
            size = len(raw)
            if declared and declared.isdigit() and size >= self.max_body:
                size = int(declared)
            observation = Observation(
                url=url,
                channel=self.kind,
                channel_name=self.name,
                status=response.status_code,
                final_url=str(response.url),
                body_size=size,
                headers={
                    k.lower(): v
                    for k, v in response.headers.items()
                    if k.lower() in DISCRIMINATING_HEADERS
                },
                excerpt=_clean_excerpt(body, self.excerpt_chars),
                redirect_chain=[h.status_code for h in response.history],
                elapsed_ms=(time.monotonic() - started) * 1000.0,
            )
            response.close()
            return observation
        except ChannelUnavailable:
            raise
        except Exception as exc:  # réseau, TLS, DNS, timeout : tout est une donnée
            return Observation(
                url=url,
                channel=self.kind,
                channel_name=self.name,
                status=None,
                error=f"{type(exc).__name__}: {exc}"[:300],
                elapsed_ms=(time.monotonic() - started) * 1000.0,
            )


def _clean_excerpt(body: str, limit: int) -> str:
    """Réduit un corps HTML à un extrait citable : espaces normalisés, longueur bornée."""
    return " ".join(body[: limit * 4].split())[:limit]


class BrowserChannel(BaseChannel):
    """Interface d'un canal navigateur : ce que voit l'agent, et non le client HTTP.

    Un navigateur diffère du HTTP direct sur quatre points qui changent le verdict :

    1. il exécute le JavaScript, donc résout les challenges anti-bot par calcul (le 202
       ``x-amzn-waf-action: challenge`` de Booking devient une page réelle) ;
    2. il présente une empreinte TLS/JA3 et un jeu d'en-têtes cohérents, que les WAF
       traitent différemment ;
    3. il sort souvent par une IP différente (résidentielle, ou un pool réputé du
       fournisseur) ;
    4. il rend le DOM, ce qui seul permet de distinguer une page vide d'une page pleine.

    `PlaywrightChannel` pilote un navigateur local, `RecordedChannel` rejoue une session de
    navigateur cloud. Les deux respectent la même règle : indisponible ⇒ le dire.
    """

    kind: Channel = Channel.BROWSER_LOCAL
    name: str = "browser"

    @abstractmethod
    def fetch(self, url: str, *, timeout: float | None = None) -> Observation: ...


# Exécuter ce canal élargirait la base du facteur κ = 0.40 de `scoring.py`, calculé sur
# 3 blocages seulement, dont 2 ont répondu au navigateur (runs/l2_probe_20260815.json).
class PlaywrightChannel(BrowserChannel):
    """Canal navigateur local piloté par Playwright, implémentation optionnelle.

    Non exécutée dans la campagne du 15/08 (Playwright absent de l'environnement de
    mesure) : ``available()`` renvoie alors ``False`` et ``fetch`` lève
    `ChannelUnavailable` plutôt que de produire une observation inventée.

    Installation :

        pip install playwright && playwright install chromium

    Args:
        headless: exécution sans fenêtre. Attention, plusieurs WAF détectent le mode
            headless ; pour reproduire le canal « navigateur cloud », il faut au minimum
            un contexte avec locale, fuseau et viewport réalistes.
        wait_until: événement d'arrêt du chargement (``"domcontentloaded"`` par défaut ;
            ``"networkidle"`` laisse le temps aux challenges JS de se résoudre).
        kind: canal générique déclaré (`BROWSER_LOCAL` ou `BROWSER_CLOUD` selon le lieu
            d'exécution effectif du navigateur).
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        wait_until: str = "domcontentloaded",
        timeout: float = 30.0,
        excerpt_chars: int = 1_200,
        kind: Channel = Channel.BROWSER_LOCAL,
    ) -> None:
        self.headless = headless
        self.wait_until = wait_until
        self.timeout = timeout
        self.excerpt_chars = excerpt_chars
        self.kind = kind
        self.name = f"playwright:{'headless' if headless else 'headed'}"

    def available(self) -> bool:
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError:
            return False
        return True

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "available": self.available(),
            "headless": self.headless,
            "wait_until": self.wait_until,
            "note": (
                "Implémentation optionnelle, non exécutée dans la campagne du 15/08/2026 "
                "(Playwright absent de l'environnement de mesure)."
            ),
        }

    def fetch(self, url: str, *, timeout: float | None = None) -> Observation:
        if not self.available():
            raise ChannelUnavailable(
                "Playwright n'est pas installé : `pip install playwright && "
                "playwright install chromium`"
            )
        from playwright.sync_api import sync_playwright  # pragma: no cover

        started = time.monotonic()  # pragma: no cover
        with sync_playwright() as p:  # pragma: no cover
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_page()
            try:
                response = page.goto(
                    url,
                    wait_until=self.wait_until,
                    timeout=(timeout or self.timeout) * 1000,
                )
                body = page.content()
                headers = dict(response.headers) if response else {}
                observation = Observation(
                    url=url,
                    channel=self.kind,
                    channel_name=self.name,
                    status=response.status if response else None,
                    final_url=page.url,
                    body_size=len(body.encode("utf-8")),
                    headers={
                        k.lower(): v
                        for k, v in headers.items()
                        if k.lower() in DISCRIMINATING_HEADERS
                    },
                    excerpt=_clean_excerpt(body, self.excerpt_chars),
                    elapsed_ms=(time.monotonic() - started) * 1000.0,
                    meta={"title": page.title(), "rendered": True},
                )
            except Exception as exc:
                observation = Observation(
                    url=url,
                    channel=self.kind,
                    channel_name=self.name,
                    error=f"{type(exc).__name__}: {exc}"[:300],
                    elapsed_ms=(time.monotonic() - started) * 1000.0,
                )
            finally:
                browser.close()
        return observation  # pragma: no cover


class RecordedChannel(BaseChannel):
    """Rejoue des observations enregistrées, sans accès réseau.

    Deux usages : transporter une mesure faite ailleurs (les observations « navigateur
    cloud » du 15/08/2026 viennent d'un pilote externe, Browserbase, et sont traitées par
    le même classifieur que les autres), et recalculer un chiffre publié une fois que les
    sites auront changé.

    Args:
        observations: observations en mémoire, ou chemin d'un JSON les contenant
            (soit une liste, soit un objet ``{"observations": [...]}``).
        kind: canal générique déclaré pour ces observations.
        name: nom de l'instance.
        source: description de la provenance, recopiée dans le rapport.
        strict: si vrai, une URL absente de l'enregistrement lève ; sinon elle produit une
            observation vide portant ``error`` (utile pour une couverture partielle).
    """

    def __init__(
        self,
        observations: Iterable[Observation] | Mapping[str, Any] | str | Path,
        *,
        kind: Channel = Channel.BROWSER_CLOUD,
        name: str = "recorded",
        source: str | None = None,
        strict: bool = False,
    ) -> None:
        self.kind = kind
        self.name = name
        self.source = source
        self.strict = strict
        self._by_url: dict[str, Observation] = {}
        for obs in _coerce_observations(observations, kind=kind, name=name):
            self._by_url[obs.url] = obs

    @property
    def urls(self) -> list[str]:
        return list(self._by_url)

    def available(self) -> bool:
        return bool(self._by_url)

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "available": self.available(),
            "source": self.source,
            "n_observations": len(self._by_url),
            "note": "Observations rejouées : aucun accès réseau au moment de l'analyse.",
        }

    def fetch(self, url: str, *, timeout: float | None = None) -> Observation:
        obs = self._by_url.get(url)
        if obs is not None:
            return obs
        if self.strict:
            raise ChannelUnavailable(f"aucune observation enregistrée pour {url}")
        return Observation(
            url=url,
            channel=self.kind,
            channel_name=self.name,
            error="not_recorded: URL absente de l'enregistrement",
        )


def _coerce_observations(
    payload: Iterable[Observation] | Mapping[str, Any] | str | Path,
    *,
    kind: Channel,
    name: str,
) -> list[Observation]:
    """Accepte des `Observation`, des dictionnaires, ou un chemin de fichier JSON."""
    if isinstance(payload, (str, Path)):
        raw = json.loads(Path(payload).read_text(encoding="utf-8"))
    else:
        raw = payload
    if isinstance(raw, Mapping):
        raw = raw.get("observations", [])
    out: list[Observation] = []
    for item in raw:  # type: ignore[union-attr]
        if isinstance(item, Observation):
            out.append(item)
            continue
        data = dict(item)
        data.setdefault("channel", kind)
        data.setdefault("channel_name", name)
        out.append(Observation.from_dict(data))
    return out
