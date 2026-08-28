"""L2 — classification des signatures d'accès (T3 accès refusé, T2 contenu disparu).

Un détecteur de liveness naïf teste ``status == 200`` et déclare la tâche vivante. Trois
mesures du 15/08/2026 suffisent à l'invalider :

- ``booking.com`` renvoie 202 avec 3 962 octets et l'en-tête ``x-amzn-waf-action:
  challenge`` : un 2xx qui n'est pas le site ;
- ``allrecipes.com`` renvoie 402 avec un cookie ``__cf_bm`` : ce n'est pas une erreur de
  serveur, c'est le pay-per-crawl de Cloudflare, un refus commercial d'être crawlé, qui
  disparaît dès qu'on regarde depuis un navigateur ;
- ``github.com`` renvoie 400 avec un corps JSON qui renvoie à la documentation d'un
  proxy : la réponse n'a jamais été produite par GitHub, mais par le proxy d'egress de la
  machine de mesure.

D'où une classification en signatures plutôt qu'en booléen, et une règle de précédence
stricte : avant d'imputer quoi que ce soit au site, éliminer ce qui est imputable au
canal. `Signature.CHANNEL_BLOCKED` est évaluée en premier ; sans elle, la campagne aurait
déclaré mortes les 41 tâches GitHub du benchmark, soit 6,4 % du corpus.

Aux signatures d'accès proprement dites (`OK`, `DEAD_404`, `PAYWALL_402`,
`FORBIDDEN_403`, `ANTIBOT_CHALLENGE`, `CAPTCHA`, `REDIRECT_HOME`, `SOFT_404`,
`SERVER_ERROR`) s'ajoutent trois signatures qui disent l'impossibilité de conclure :
`CHANNEL_BLOCKED`, `UNREACHABLE`, `RATE_LIMITED`. Toutes portent le canal, le code, la
taille du corps, les en-têtes discriminants et un extrait.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from ..channels import BaseChannel, Observation
from ..models import Category, Channel, Finding, Severity, Task

__all__ = [
    "Signature",
    "Vendor",
    "LivenessVerdict",
    "ChannelComparison",
    "classify",
    "detect_vendor",
    "probe_url",
    "probe_task",
    "detect_liveness",
    "ANTIBOT_BODY_MAX",
]

DETECTOR_NAME = "l2_liveness"

#: Au-delà de cette taille, un corps 2xx est considéré comme une vraie page.
#: Calibré sur les mesures du 15/08 : les interstitiels observés pèsent 612 o (Cloudflare
#: 402), 1 987 o (AWS WAF ESPN) et 3 962 o (AWS WAF Booking) ; la plus petite vraie page
#: d'accueil du corpus, Google Maps, en pèse 57 487. La marge est donc large — le seuil
#: n'est de toute façon jamais utilisé seul, mais en conjonction avec un marqueur éditeur.
ANTIBOT_BODY_MAX = 15_000

#: Sous cette taille, un 2xx sans aucun marqueur reste suspect (page coquille).
EMPTY_BODY_MAX = 1_500


class Vendor(str, Enum):
    """Éditeur du dispositif de filtrage identifié, quand il l'est.

    Nommé pour distinguer un blocage contractuel (pay-per-crawl) d'une défense contre
    l'abus (challenge JS).
    """

    CLOUDFLARE = "cloudflare"
    AWS_WAF = "aws_waf"
    PERIMETERX = "perimeterx"
    DATADOME = "datadome"
    IMPERVA = "imperva"
    AKAMAI = "akamai"
    KASADA = "kasada"
    RECAPTCHA = "recaptcha"
    HCAPTCHA = "hcaptcha"
    UNKNOWN = "unknown"
    NONE = "none"


class Signature(str, Enum):
    """Signature d'accès observée pour une URL depuis un canal donné."""

    #: Le site a répondu et la réponse ressemble à la vraie page.
    OK = "ok"
    #: 404/410 : la ressource a disparu, le site l'assume.
    DEAD_404 = "dead_404"
    #: 402 : accès conditionné à un paiement (pay-per-crawl Cloudflare).
    PAYWALL_402 = "paywall_402"
    #: 403 : refus explicite du site pour ce client.
    FORBIDDEN_403 = "forbidden_403"
    #: 429 : limitation de débit — état transitoire, à ne pas confondre avec un refus.
    RATE_LIMITED = "rate_limited_429"
    #: 5xx : panne côté site, transitoire par nature.
    SERVER_ERROR = "server_error_5xx"
    #: 2xx dont le corps est un interstitiel de vérification, pas le site.
    ANTIBOT_CHALLENGE = "antibot_challenge"
    #: Interstitiel exigeant une résolution humaine (reCAPTCHA, hCaptcha, DataDome).
    CAPTCHA = "captcha"
    #: URL profonde absorbée par la racine du site : contenu retiré sans 404.
    REDIRECT_HOME = "redirect_home"
    #: 200 dont le corps annonce une page introuvable, ou est vide de contenu.
    SOFT_404 = "soft_404"
    #: La réponse vient de l'infrastructure de mesure, pas du site. **Non imputable.**
    CHANNEL_BLOCKED = "channel_blocked"
    #: Aucune réponse HTTP (DNS, TLS, délai dépassé). **Non imputable sans réplication.**
    UNREACHABLE = "unreachable"

    @property
    def is_site_verdict(self) -> bool:
        """Vrai si la signature dit quelque chose du **site** (et non du canal).

        Seules ces signatures ont le droit d'entrer dans un taux de decay publié.
        """
        return self not in (Signature.CHANNEL_BLOCKED, Signature.UNREACHABLE)

    @property
    def blocks_task(self) -> bool:
        """Vrai si un agent lancé sur cette URL ne verrait pas le site attendu."""
        return self not in (Signature.OK, Signature.CHANNEL_BLOCKED)


#: Sévérité et confiance par signature. Deux axes séparés, conformément à `models` : la
#: sévérité dit la gravité si le constat est vrai, la confiance la solidité du constat.
_SIGNATURE_POLICY: dict[Signature, tuple[Category, Severity, float, str]] = {
    Signature.OK: (
        Category.ACCESS_DENIED,
        Severity.INFO,
        0.90,
        "le site répond et la réponse ressemble à la page attendue",
    ),
    Signature.DEAD_404: (
        Category.CONTENT_DRIFT,
        Severity.CRITICAL,
        0.95,
        "ressource supprimée : le site répond 404/410",
    ),
    Signature.PAYWALL_402: (
        Category.ACCESS_DENIED,
        Severity.HIGH,
        0.90,
        "pay-per-crawl : l'accès automatisé est conditionné à un paiement",
    ),
    Signature.FORBIDDEN_403: (
        Category.ACCESS_DENIED,
        Severity.HIGH,
        0.85,
        "refus explicite du site pour ce type de client",
    ),
    Signature.RATE_LIMITED: (
        Category.ACCESS_DENIED,
        Severity.MEDIUM,
        0.60,
        "limitation de débit : état transitoire, à re-sonder avant conclusion",
    ),
    Signature.SERVER_ERROR: (
        Category.ACCESS_DENIED,
        Severity.MEDIUM,
        0.50,
        "erreur serveur : probablement transitoire",
    ),
    Signature.ANTIBOT_CHALLENGE: (
        Category.ACCESS_DENIED,
        Severity.HIGH,
        0.85,
        "interstitiel de vérification : le corps 2xx n'est pas la page du site",
    ),
    Signature.CAPTCHA: (
        Category.ACCESS_DENIED,
        Severity.CRITICAL,
        0.90,
        "CAPTCHA : résolution humaine exigée, l'agent ne peut pas passer",
    ),
    Signature.REDIRECT_HOME: (
        Category.CONTENT_DRIFT,
        Severity.HIGH,
        0.75,
        "URL profonde redirigée vers l'accueil : contenu retiré sans 404",
    ),
    Signature.SOFT_404: (
        Category.CONTENT_DRIFT,
        Severity.HIGH,
        0.60,
        "200 annonçant une page introuvable ou vide de contenu",
    ),
    Signature.CHANNEL_BLOCKED: (
        Category.ACCESS_DENIED,
        Severity.INFO,
        0.90,
        "réponse fabriquée par l'infrastructure de mesure : non imputable au site",
    ),
    Signature.UNREACHABLE: (
        Category.ACCESS_DENIED,
        Severity.LOW,
        0.35,
        "aucune réponse HTTP : imputation impossible sans réplication sur un autre canal",
    ),
}


#: Marqueurs par éditeur : (en-têtes, motifs de corps). Les en-têtes sont plus fiables
#: que le corps — un site peut citer « cloudflare » dans son pied de page.
_VENDOR_HEADERS: dict[Vendor, tuple[str, ...]] = {
    Vendor.CLOUDFLARE: ("cf-ray", "cf-mitigated", "cf-cache-status"),
    Vendor.AWS_WAF: ("x-amzn-waf-action",),
    Vendor.DATADOME: ("x-datadome", "x-datadome-cid"),
    Vendor.IMPERVA: ("x-iinfo", "x-cdn"),
    Vendor.AKAMAI: ("x-akamai-transformed",),
    Vendor.KASADA: ("x-kpsdk-ct",),
}

#: Éditeur déductible du seul en-tête ``Server``. Amazon alterne, d'un tirage à l'autre,
#: entre un interstitiel AWS WAF (202) et un interstitiel **Akamai Bot Manager** (200,
#: ``server: AkamaiGHost``, cookie ``ak_bmsc``, méta-rafraîchissement ``bm-verify``) :
#: sans cette table, la seconde variante passait pour une page normale.
_VENDOR_SERVER: tuple[tuple[str, Vendor], ...] = (
    ("cloudflare", Vendor.CLOUDFLARE),
    ("akamaighost", Vendor.AKAMAI),
    ("akamai", Vendor.AKAMAI),
    ("datadome", Vendor.DATADOME),
    ("imperva", Vendor.IMPERVA),
    ("incapsula", Vendor.IMPERVA),
)

_VENDOR_BODY: dict[Vendor, re.Pattern[str]] = {
    Vendor.CLOUDFLARE: re.compile(
        r"cdn-cgi/challenge-platform|__cf_chl|cf_chl_opt|just a moment\.\.\.|"
        r"attention required!\s*\|\s*cloudflare|ray id",
        re.I,
    ),
    Vendor.AWS_WAF: re.compile(
        r"awswafcookiedomainlist|token\.awswaf\.com|awswaf\b|challenge\.js|"
        # Variantes de l'interstitiel AWS WAF observées le 15/08 sur Booking : le nom
        # de l'éditeur n'apparaît pas toujours, mais ces fonctions du script si.
        r"reportchallengeerror|challenge-container|window\.gokuprops",
        re.I,
    ),
    Vendor.PERIMETERX: re.compile(r"perimeterx|_px[A-Za-z0-9]{0,4}\b|px-captcha", re.I),
    Vendor.DATADOME: re.compile(r"datadome|geo\.captcha-delivery\.com", re.I),
    Vendor.IMPERVA: re.compile(r"_incapsula_resource|incap_ses|imperva", re.I),
    Vendor.AKAMAI: re.compile(
        r"akamai|reference\s*#\d|_abck|ak_bmsc|bm-verify|akamaighost", re.I
    ),
    Vendor.KASADA: re.compile(r"kpsdk|kasada", re.I),
    Vendor.RECAPTCHA: re.compile(r"g-recaptcha|recaptcha/api\.js|www\.google\.com/recaptcha", re.I),
    Vendor.HCAPTCHA: re.compile(r"hcaptcha\.com|h-captcha", re.I),
}

#: Formulations d'un interstitiel de vérification, indépendamment de l'éditeur.
_CHALLENGE_TEXT = re.compile(
    r"verify(?:ing)?\s+you\s+are\s+(?:a\s+)?human|checking\s+your\s+browser|"
    r"enable\s+javascript\s+and\s+cookies\s+to\s+continue|"
    r"unusual\s+traffic|automated\s+(?:requests|queries)|"
    r"are\s+you\s+a\s+robot|bot\s+detection|access\s+denied",
    re.I,
)

#: Un corps 2xx dont le contenu utile se réduit à un méta-rafraîchissement porteur d'un
#: jeton de vérification : c'est la forme canonique de l'interstitiel Akamai Bot Manager.
_META_REFRESH_CHALLENGE = re.compile(
    r"""<meta[^>]+http-equiv=["']?refresh["']?[^>]+(?:bm-verify|_abck|challenge|verify)""",
    re.I,
)

#: Un document HTML servi avec un titre vide n'est pas une page de site : tous les sites
#: du corpus en posent un. Les interstitiels AWS WAF, eux, laissent ``<title></title>``.
#: C'est le garde-fou pour les variantes de challenge servies en 200 plutôt qu'en 202.
_EMPTY_TITLE = re.compile(r"<title[^>]*>\s*</title>", re.I)

#: Formulations exigeant une action humaine — plus grave qu'un challenge calculable.
_CAPTCHA_TEXT = re.compile(
    r"\bcaptcha\b|enter\s+the\s+characters\s+you\s+see|"
    r"select\s+all\s+images|i'?m\s+not\s+a\s+robot|solve\s+the\s+puzzle",
    re.I,
)

#: Formulations d'une page « introuvable » servie en 200.
_SOFT_404_TEXT = re.compile(
    r"page\s+not\s+found|404\s*[-–—:|]?\s*(?:not\s+found|page)|"
    r"we\s+can(?:no|')t\s+find|couldn'?t\s+find\s+(?:the\s+)?page|"
    r"no\s+longer\s+(?:available|exists)|has\s+been\s+removed|"
    r"sorry,?\s+(?:this|that)\s+page|the\s+page\s+you\s+(?:requested|were\s+looking)",
    re.I,
)

#: Marqueur de paiement dans un corps 402 — distingue le pay-per-crawl d'un vrai paywall
#: éditorial (« subscribe to read ») qui, lui, relève du contenu et non de l'accès.
_PAYWALL_TEXT = re.compile(
    r"pay[\s\-]?per[\s\-]?crawl|payment\s+required|access\s+issue|"
    r"crawler\s+(?:access|licen[cs])",
    re.I,
)


def detect_vendor(observation: Observation) -> Vendor:
    """Identifie l'éditeur du dispositif de filtrage, en-têtes d'abord.

    Renvoie `Vendor.NONE` quand rien n'indique de dispositif, `Vendor.UNKNOWN` quand un
    texte de challenge est présent sans signature d'éditeur reconnue.
    """
    server = (observation.header("server") or "").lower()
    for vendor, names in _VENDOR_HEADERS.items():
        if any(observation.header(h) for h in names):
            return vendor
    for needle, vendor in _VENDOR_SERVER:
        if needle in server:
            return vendor
    body = observation.excerpt or ""
    cookies = observation.header("set-cookie") or ""
    blob = f"{body} {cookies}"
    for vendor in (
        Vendor.RECAPTCHA,
        Vendor.HCAPTCHA,
        Vendor.DATADOME,
        Vendor.PERIMETERX,
        Vendor.KASADA,
        Vendor.IMPERVA,
        Vendor.AWS_WAF,
        Vendor.CLOUDFLARE,
        Vendor.AKAMAI,
    ):
        pattern = _VENDOR_BODY.get(vendor)
        if pattern and pattern.search(blob):
            return vendor
    if _CHALLENGE_TEXT.search(body) or _CAPTCHA_TEXT.search(body):
        return Vendor.UNKNOWN
    return Vendor.NONE


@dataclass(frozen=True, slots=True)
class LivenessVerdict:
    """Verdict de liveness pour une URL, un canal et un instant."""

    url: str
    signature: Signature
    channel: Channel
    channel_name: str
    status: int | None
    body_size: int
    vendor: Vendor
    headers: Mapping[str, str]
    excerpt: str
    rationale: str
    confidence: float
    observed_at: _dt.datetime
    final_url: str | None = None
    redirect_chain: Sequence[int] = field(default_factory=tuple)
    elapsed_ms: float | None = None
    error: str | None = None

    @property
    def is_site_verdict(self) -> bool:
        return self.signature.is_site_verdict

    @property
    def blocks_task(self) -> bool:
        return self.signature.blocks_task

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "signature": self.signature.value,
            "channel": self.channel.value,
            "channel_name": self.channel_name,
            "status": self.status,
            "body_size": self.body_size,
            "vendor": self.vendor.value,
            "headers": dict(self.headers),
            "excerpt": self.excerpt[:400],
            "rationale": self.rationale,
            "confidence": round(self.confidence, 3),
            "observed_at": self.observed_at.isoformat(),
            "final_url": self.final_url,
            "redirect_chain": list(self.redirect_chain),
            "elapsed_ms": round(self.elapsed_ms, 1) if self.elapsed_ms is not None else None,
            "error": self.error,
            "is_site_verdict": self.is_site_verdict,
            "blocks_task": self.blocks_task,
        }


def classify(observation: Observation) -> LivenessVerdict:
    """Classe une observation en signature d'accès.

    Ordre de précédence, du plus « imputable au canal » au plus « imputable au site » :

    1. réponse fabriquée par le proxy d'egress → `CHANNEL_BLOCKED` ;
    2. aucune réponse HTTP → `UNREACHABLE` ;
    3. CAPTCHA (quel que soit le code) → `CAPTCHA` ;
    4. codes explicites : 402 → `PAYWALL_402`, 403 → `FORBIDDEN_403`, 404/410 →
       `DEAD_404`, 429 → `RATE_LIMITED`, 5xx → `SERVER_ERROR` ;
    5. 2xx : interstitiel (`ANTIBOT_CHALLENGE`), redirection vers l'accueil
       (`REDIRECT_HOME`), page introuvable déguisée (`SOFT_404`), sinon `OK`.

    Un 403 accompagné d'un marqueur d'éditeur anti-bot reste classé `FORBIDDEN_403` — le
    fournisseur est consigné dans ``vendor``. Fusionner les deux ferait perdre la
    distinction entre « le site me refuse » et « le site me teste ».
    """
    vendor = detect_vendor(observation)
    body = observation.excerpt or ""
    common = {
        "url": observation.url,
        "channel": observation.channel,
        "channel_name": observation.channel_name,
        "status": observation.status,
        "body_size": observation.body_size,
        "vendor": vendor,
        "headers": dict(observation.headers),
        "excerpt": observation.excerpt,
        "observed_at": observation.observed_at,
        "final_url": observation.final_url,
        "redirect_chain": observation.redirect_chain,
        "elapsed_ms": observation.elapsed_ms,
        "error": observation.error,
    }

    def verdict(sig: Signature, why: str, *, confidence: float | None = None) -> LivenessVerdict:
        _, _, default_confidence, _ = _SIGNATURE_POLICY[sig]
        return LivenessVerdict(
            signature=sig,
            rationale=why,
            confidence=default_confidence if confidence is None else confidence,
            **common,  # type: ignore[arg-type]
        )

    # 1. Le canal a répondu à la place du site.
    if observation.looks_proxy_mediated:
        return verdict(
            Signature.CHANNEL_BLOCKED,
            "corps ou erreur produits par l'infrastructure de mesure (politique d'egress) : "
            "aucune conclusion sur le site n'est permise depuis ce canal",
        )

    # 2. Rien n'est revenu.
    if not observation.reached:
        return verdict(
            Signature.UNREACHABLE,
            f"aucune réponse HTTP ({observation.error or 'cause inconnue'})",
        )

    status = int(observation.status or 0)

    # 3. CAPTCHA : le seul cas où un humain est structurellement requis.
    if _CAPTCHA_TEXT.search(body) or vendor in (Vendor.RECAPTCHA, Vendor.HCAPTCHA):
        return verdict(
            Signature.CAPTCHA,
            f"marqueur de CAPTCHA dans la réponse {status} (éditeur : {vendor.value})",
        )

    # 4. Codes explicites.
    if status == 402:
        paywall = "pay-per-crawl" if _PAYWALL_TEXT.search(body) else "402 sans texte explicite"
        return verdict(
            Signature.PAYWALL_402,
            f"402 Payment Required ({paywall}, éditeur : {vendor.value}, "
            f"corps de {observation.body_size} o)",
        )
    if status in (401, 403):
        # 401 est rangé ici plutôt qu'à part : plusieurs API répondent 401 pour une
        # ressource *inexistante* afin de ne pas divulguer l'existence des ressources
        # privées (Hugging Face le fait). Le code seul ne tranche donc pas entre « je
        # refuse » et « ça n'existe pas » ; c'est au résolveur de `l2_content`, qui
        # connaît l'API interrogée, de le faire.
        return verdict(
            Signature.FORBIDDEN_403,
            f"{status} (éditeur : {vendor.value}, corps de {observation.body_size} o)"
            + (
                " — plusieurs API renvoient 401 pour une ressource inexistante"
                if status == 401
                else ""
            ),
        )
    if status in (404, 410):
        return verdict(Signature.DEAD_404, f"{status} : la ressource n'existe plus")
    if status == 429:
        retry = observation.header("retry-after")
        return verdict(
            Signature.RATE_LIMITED,
            "429 Too Many Requests" + (f" (Retry-After: {retry})" if retry else ""),
        )
    if status >= 500:
        return verdict(Signature.SERVER_ERROR, f"{status} : erreur côté serveur")
    if 300 <= status < 400 and not observation.final_url:
        return verdict(
            Signature.REDIRECT_HOME,
            f"{status} non suivi : destination inconnue",
            confidence=0.30,
        )

    # 5. Les 2xx, où tout se joue.
    if 200 <= status < 300:
        small = observation.body_size <= ANTIBOT_BODY_MAX
        challenged = (
            bool(_CHALLENGE_TEXT.search(body))
            or bool(_META_REFRESH_CHALLENGE.search(body))
            or (bool(_EMPTY_TITLE.search(body)) and small)
        )
        waf_action = (observation.header("x-amzn-waf-action") or "").lower()
        vendor_marker = vendor not in (Vendor.NONE, Vendor.UNKNOWN)

        # RFC 9110 §15.3.3 : 202 signifie « requête acceptée, traitement non terminé » ;
        # aucun site ne sert son accueil ainsi, mais les WAF s'en servent pour livrer un
        # interstitiel. Booking alterne des interstitiels de 3 962 et 7 033 octets sous le
        # même 202, et la variante longue enfouit son marqueur d'éditeur trop loin pour un
        # extrait court : trancher sur le code plutôt que sur le corps est plus stable.
        if status == 202:
            return verdict(
                Signature.ANTIBOT_CHALLENGE,
                f"202 Accepted sur une requête de document ({observation.body_size} o, "
                f"éditeur : {vendor.value}) : un site ne sert pas une page en 202 — "
                "réponse d'interstitiel",
                confidence=0.90 if vendor_marker or challenged else 0.70,
            )

        # 5a. Le WAF annonce lui-même qu'il sert un challenge : preuve directe.
        if waf_action in ("challenge", "captcha"):
            sig = Signature.CAPTCHA if waf_action == "captcha" else Signature.ANTIBOT_CHALLENGE
            return verdict(
                sig,
                f"{status} avec x-amzn-waf-action: {waf_action} — la réponse est un "
                f"interstitiel AWS WAF de {observation.body_size} o, pas la page du site",
                confidence=0.95,
            )
        # 5b. Corps court + marqueur d'éditeur ou texte de challenge : faisceau d'indices.
        if small and (vendor_marker or challenged):
            return verdict(
                Signature.ANTIBOT_CHALLENGE,
                f"{status} avec un corps de {observation.body_size} o "
                f"(≤ {ANTIBOT_BODY_MAX}) portant un marqueur {vendor.value} : "
                "interstitiel de vérification, pas la page attendue",
            )
        # 5c. Le site annonce lui-même une page absente, en 200.
        if _SOFT_404_TEXT.search(body[:800]):
            return verdict(
                Signature.SOFT_404,
                f"{status} dont le début du corps annonce une page introuvable",
            )
        # 5d. URL profonde absorbée par une page plus haute du même site.
        absorption = observation.redirect_absorption
        if absorption:
            where = "la racine" if absorption == "root" else f"un parent ({observation.final_path})"
            return verdict(
                Signature.REDIRECT_HOME,
                f"{observation.path} redirigé vers {where} de {observation.host} "
                f"(chaîne : {list(observation.redirect_chain) or 'côté serveur'}) : "
                "le contenu demandé n'existe pas, servi en 200",
                confidence=0.85 if absorption == "ancestor" else 0.75,
            )
        # 5e. Corps quasi vide sans explication : suspect, mais faible confiance.
        if observation.body_size <= EMPTY_BODY_MAX:
            return verdict(
                Signature.SOFT_404,
                f"{status} avec un corps de {observation.body_size} o, sans contenu "
                "identifiable ni marqueur de challenge",
                confidence=0.40,
            )
        return verdict(
            Signature.OK,
            f"{status} avec un corps de {observation.body_size} o, sans marqueur de "
            "blocage ni d'absence de contenu",
        )

    return verdict(
        Signature.UNREACHABLE,
        f"code HTTP inattendu : {status}",
        confidence=0.30,
    )


def probe_url(url: str, channel: BaseChannel, *, timeout: float | None = None) -> LivenessVerdict:
    """Sonde une URL depuis un canal et renvoie son verdict de liveness."""
    return classify(channel.fetch(url, timeout=timeout))


def probe_task(
    task: Task, channel: BaseChannel, *, timeout: float | None = None
) -> LivenessVerdict | None:
    """Sonde l'URL de départ d'une tâche. Renvoie ``None`` si la tâche n'en porte pas."""
    if not task.start_url:
        return None
    return probe_url(task.start_url, channel, timeout=timeout)


@dataclass(frozen=True, slots=True)
class ChannelComparison:
    """Verdicts d'une même URL vus depuis plusieurs canaux.

    `disagrees` donne la divergence pour une URL, `divergence_rate` son agrégat.
    """

    url: str
    verdicts: Mapping[str, LivenessVerdict]

    @property
    def signatures(self) -> dict[str, str]:
        return {name: v.signature.value for name, v in self.verdicts.items()}

    @property
    def site_verdicts(self) -> dict[str, LivenessVerdict]:
        """Verdicts réellement imputables au site (canal non bloqué, site joignable)."""
        return {n: v for n, v in self.verdicts.items() if v.is_site_verdict}

    @property
    def disagrees(self) -> bool:
        """Vrai si deux canaux imputables au site ne donnent pas la même signature."""
        sigs = {v.signature for v in self.site_verdicts.values()}
        return len(sigs) > 1

    @property
    def blocks_disagree(self) -> bool:
        """Vrai si les canaux divergent sur la question qui compte : la tâche est-elle
        exécutable ? Plus robuste que `disagrees`, qui distingue aussi 402 de 403."""
        blocked = {v.blocks_task for v in self.site_verdicts.values()}
        return len(blocked) > 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "signatures": self.signatures,
            "disagrees": self.disagrees,
            "blocks_disagree": self.blocks_disagree,
            "verdicts": {n: v.to_dict() for n, v in self.verdicts.items()},
        }


def divergence_rate(comparisons: Iterable[ChannelComparison]) -> dict[str, Any]:
    """Taux de divergence inter-canaux sur un ensemble d'URL.

    Ne compte que les URL pour lesquelles **au moins deux canaux** ont produit un verdict
    imputable au site : comparer un verdict à un blocage de canal n'a pas de sens.
    """
    items = [c for c in comparisons if len(c.site_verdicts) >= 2]
    if not items:
        return {"n_comparable": 0, "n_disagree": 0, "rate": None, "n_blocks_disagree": 0}
    disagree = [c for c in items if c.disagrees]
    blocks = [c for c in items if c.blocks_disagree]
    return {
        "n_comparable": len(items),
        "n_disagree": len(disagree),
        "rate": round(len(disagree) / len(items), 4),
        "n_blocks_disagree": len(blocks),
        "blocks_rate": round(len(blocks) / len(items), 4),
        "disagreeing_urls": [c.url for c in disagree],
    }


def finding_from_verdict(verdict: LivenessVerdict, task: Task | None = None) -> Finding:
    """Convertit un verdict de liveness en constat de la taxonomie."""
    category, severity, _, rationale = _SIGNATURE_POLICY[verdict.signature]
    return Finding(
        category=category,
        severity=severity,
        confidence=verdict.confidence,
        evidence=verdict.excerpt[:300] or verdict.rationale,
        detector=DETECTOR_NAME,
        channel=verdict.channel,
        task_id=task.task_id if task else None,
        signal=verdict.signature.value,
        details={
            "url": verdict.url,
            "status": verdict.status,
            "body_size": verdict.body_size,
            "vendor": verdict.vendor.value,
            "headers": dict(verdict.headers),
            "final_url": verdict.final_url,
            "channel_name": verdict.channel_name,
            "rationale": verdict.rationale,
            "taxonomy_note": rationale,
            "is_site_verdict": verdict.is_site_verdict,
        },
        observed_at=verdict.observed_at.date(),
    )


def detect_liveness(
    task: Task,
    *,
    channel: BaseChannel,
    today: _dt.date | None = None,
    timeout: float | None = None,
) -> list[Finding]:
    """Détecteur L2 : sonde l'URL de départ d'une tâche et en tire un constat.

    Contrairement aux détecteurs L1, celui-ci exige un canal explicite : il n'y a pas
    d'observation par défaut, et un appel sans canal serait une mesure sans provenance.
    """
    verdict = probe_task(task, channel, timeout=timeout)
    if verdict is None:
        return []
    finding = finding_from_verdict(verdict, task)
    if today is not None:
        finding = Finding(
            category=finding.category,
            severity=finding.severity,
            confidence=finding.confidence,
            evidence=finding.evidence,
            detector=finding.detector,
            channel=finding.channel,
            task_id=finding.task_id,
            signal=finding.signal,
            details=finding.details,
            observed_at=today,
        )
    return [finding]


detect_liveness.name = DETECTOR_NAME  # type: ignore[attr-defined]
