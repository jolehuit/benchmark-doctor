"""Contrôle de non-fuite : la rubrique du juge L3 ne doit rien emprunter au corpus évalué.

Le problème B1 de la vérification adverse du 16/08/2026 tenait à quatre énoncés du jeu
annoté recopiés mot pour mot dans le prompt du juge (`GitHub--5`, `Coursera--0`,
`Huggingface--23`, `Apple--11`), tous étiquetés positifs. Un tel défaut se réintroduit à
la première réécriture distraite de ``_RUBRIC`` : ce script en fait un test exécutable,
et il **échoue sur l'ancienne rubrique** (``--old`` le rejoue pour le montrer).

Quatre contrôles, du plus littéral au plus exigeant :

1. **Verbatim** — aucune suite de 4 mots (mots outils compris) d'un des 643 énoncés de
   WebVoyager n'apparaît dans la rubrique. C'est le contrôle qui aurait dû exister.
2. **Domaines** — la rubrique ne nomme aucun des quinze sites du corpus ni leurs
   marqueurs de domaine (``recipe``, ``repo``, ``iPad``, ``hotel``, ``university``…).
   C'est ce contrôle qui condamne l'ancienne rubrique : huit marqueurs, dont les quatre
   sites qui ne portent aucun positif.
3. **Vocabulaire des exemples** — chaque mot de contenu des *illustrations* (les seuls
   fragments entre guillemets ou entre parenthèses : le reste est la définition, qu'on ne
   peut pas écrire sans anglais courant) est soit absent du corpus, soit présent dans au
   moins ``MIN_GENERIC_DF`` énoncés. Le régime intermédiaire — un mot rare partagé avec
   quelques énoncés — est la signature d'une fuite par paraphrase.
4. **Recouvrement lexical** — pour chaque énoncé annoté, la part de ses mots de contenu
   présents dans la rubrique reste sous ``MAX_OVERLAP``.

Aucun de ces contrôles ne traite la fuite **structurelle** restante : le juge reçoit
toujours la définition de l'étiquette, celle-là même qu'a suivie l'annotateur. Elle n'est
pas corrigeable par une réécriture de prompt ; elle est mesurée par la ligne « prompt
plain » et discutée dans `experiments/ABLATION_L3.md`.

    python experiments/check_rubric_leak.py          # rubrique courante
    python experiments/check_rubric_leak.py --old    # contrôle négatif : l'ancienne
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark_doctor.detectors.l3_ambiguity import _RUBRIC  # noqa: E402

CORPUS = ROOT / "data" / "raw" / "webvoyager_original.jsonl"
ANNOTATIONS = ROOT / "data" / "annotations_ambiguity.json"

#: La rubrique du 15/08/2026, conservée comme contrôle négatif du test.
LEAKY_RUBRIC = '''A web-agent benchmark task is AMBIGUOUS when, reading the statement alone, two
different answers can both be equally correct because the statement gives no
tie-breaking criterion and the website imposes no deterministic order.

Consider ambiguous:
- several items satisfy the stated filters and nothing selects one of them
  ("find a hotel rated above 8.0", "a Python repo with at least 500 stars");
- the selection criterion is subjective or is not a property the site exposes
  ("best", "popular", "renowned university", "innovative and widely recognized");
- the referent or the category is not determined ("the latest iPad model" when several
  iPad lines exist; a section the site does not have);
- the expected output is not determined: pick k items among many equivalent ones,
  or free generation with no reference answer.

Consider NOT ambiguous:
- a deterministic order given by the statement or by the site decides the answer, or its
  prefix when the statement is plural (cheapest, most starred, most recent, a named
  section, a named entry);
- a named, unique object (a dictionary word, a named repository, a named course, a fully
  specified product configuration, a computation);
- the answer varies only in FORM, not in TARGET (summarising one identified article);
- a task that is impossible, outdated or blocked is NOT ambiguous for that reason —
  judge only whether several answers would be equally correct.'''

#: Mots outils : leur coïncidence ne prouve rien et noierait les contrôles 3 et 4.
STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "at", "with", "that",
    "is", "are", "be", "it", "its", "as", "by", "from", "this", "these", "those", "not",
    "no", "if", "when", "then", "there", "their", "them", "which", "what", "who", "than",
    "can", "will", "would", "does", "do", "has", "have", "had", "was", "were", "but",
    "me", "my", "you", "your", "we", "us", "so", "also", "only", "any", "all", "each",
    "other", "same", "such", "some", "both", "between", "per", "up", "out", "into",
    "about", "over", "more", "one", "two", "three", "several", "many", "few", "own",
}

#: Marqueurs de domaine des quinze sites de WebVoyager. Leur présence signalerait un
#: exemple emprunté à l'un des sites évalués, même reformulé.
SITE_MARKERS = {
    "Allrecipes": ("allrecipes", "recipe", "ingredient", "cookie", "lasagna"),
    "Amazon": ("amazon", "add to cart", "prime"),
    "Apple": ("apple", "ipad", "iphone", "macbook", "airpods", "imac"),
    "ArXiv": ("arxiv", "preprint", "e-print"),
    "BBC News": ("bbc", "news article", "headline"),
    "Booking": ("booking.com", "hotel", "check-in date", "guesthouse"),
    "Cambridge Dictionary": ("cambridge", "dictionary", "pronunciation"),
    "Coursera": ("coursera", "course", "university", "syllabus", "instructor"),
    "ESPN": ("espn", "nba", "nfl", "standings", "roster"),
    "GitHub": ("github", "repo", "repositor", "stars", "commit", "pull request"),
    "Google Flights": ("flight", "layover", "round trip", "one-way"),
    "Google Map": ("google map", "driving directions"),
    "Google Search": ("google search",),
    "Huggingface": ("huggingface", "hugging face", "model card", "dataset"),
    "Wolfram Alpha": ("wolfram", "integral", "derivative", "solve the equation"),
}

#: Longueur minimale d'une suite de mots considérée comme du verbatim.
MIN_NGRAM = 4
#: Fréquence documentaire au-delà de laquelle un mot est de l'anglais courant, pas un
#: emprunt (5 énoncés sur 643, soit 0,8 %).
MIN_GENERIC_DF = 5
#: Part maximale des mots de contenu d'un énoncé annoté que la rubrique peut contenir.
MAX_OVERLAP = 0.60

_ILLUSTRATION_RE = re.compile(r'"[^"]*"|\([^()]*\)')


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def content_words(text: str) -> list[str]:
    return [w for w in words(text) if w not in STOPWORDS and len(w) > 2]


def ngrams(seq: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(seq[i : i + n]) for i in range(len(seq) - n + 1)}


def illustrations(rubric: str) -> list[str]:
    """Les fragments illustratifs : entre guillemets ou entre parenthèses.

    La définition, elle, ne peut pas s'écrire sans vocabulaire courant : la contraindre
    reviendrait à dégrader l'anglais de la rubrique, donc à mesurer autre chose.
    """
    return _ILLUSTRATION_RE.findall(rubric)


def check(rubric: str, *, label: str) -> int:
    corpus = [json.loads(l) for l in CORPUS.read_text(encoding="utf-8").splitlines() if l.strip()]
    annotated = json.loads(ANNOTATIONS.read_text(encoding="utf-8"))["items"]
    df: collections.Counter[str] = collections.Counter()
    for row in corpus:
        df.update(set(words(row["ques"])))

    rubric_words = words(rubric)
    rubric_ngrams = {n: ngrams(rubric_words, n) for n in range(MIN_NGRAM, 10)}
    rubric_vocab = set(content_words(rubric))
    failures: list[str] = []
    print(f"=== rubrique « {label} » — {len(corpus)} énoncés du corpus, "
          f"{len(annotated)} annotés ===")

    # -- 1. verbatim ---------------------------------------------------------------------
    shared = [
        (row["id"], g)
        for row in corpus
        for n in range(MIN_NGRAM, 10)
        for g in (ngrams(words(row["ques"]), n) & rubric_ngrams[n])
    ]
    print(f"1. suites de ≥{MIN_NGRAM} mots reprises d'un énoncé du corpus : {len(shared)}")
    for task_id, g in shared[:10]:
        print(f"     {task_id:18s} « {' '.join(g)} »")
    if shared:
        failures.append(f"{len(shared)} suites de mots du corpus présentes dans la rubrique")

    # -- 2. domaines ---------------------------------------------------------------------
    low = rubric.lower()
    hits = [(s, m) for s, ms in SITE_MARKERS.items() for m in ms if m in low]
    print(f"2. marqueurs de domaine des 15 sites : {len(hits)}")
    for site, marker in hits:
        print(f"     {site:22s} « {marker} »")
    if hits:
        failures.append(f"{len(hits)} marqueurs de domaine du corpus dans la rubrique")

    # -- 3. vocabulaire des exemples -----------------------------------------------------
    spans = illustrations(rubric)
    example_words = sorted({w for s in spans for w in content_words(s)})
    borderline = [(w, df[w]) for w in example_words if 1 <= df[w] < MIN_GENERIC_DF]
    print(f"3. {len(spans)} fragments illustratifs, {len(example_words)} mots de contenu ; "
          f"mots ni absents du corpus ni courants (1 ≤ df < {MIN_GENERIC_DF}) : {len(borderline)}")
    for w, d in borderline:
        carriers = [i["task_id"] for i in annotated if re.search(rf"\b{re.escape(w)}\b", i["question"], re.I)]
        print(f"     {w:18s} df={d:<3d} annotés porteurs : {carriers or '—'}")
    if borderline:
        failures.append(f"{len(borderline)} mots d'exemple partagés avec un petit nombre d'énoncés")

    # -- 4. recouvrement lexical ---------------------------------------------------------
    worst = sorted(
        (
            (len(set(content_words(i["question"])) & rubric_vocab)
             / max(1, len(set(content_words(i["question"])))), i["task_id"], i["label"])
            for i in annotated
        ),
        reverse=True,
    )
    print(f"4. recouvrement lexical maximal sur les énoncés annotés : {worst[0][0]:.0%} "
          f"({worst[0][1]}, label {worst[0][2]}) — plafond {MAX_OVERLAP:.0%}")
    for ratio, task_id, lab in worst[:5]:
        print(f"     {task_id:18s} label={lab} {ratio:.0%}")
    if worst[0][0] > MAX_OVERLAP:
        failures.append(f"recouvrement lexical {worst[0][0]:.0%} > {MAX_OVERLAP:.0%} ({worst[0][1]})")

    print()
    for f in failures:
        print(f"ÉCHEC : {f}")
    if not failures:
        print("rubrique propre : aucun énoncé, aucune paraphrase et aucun domaine du corpus évalué.")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--old", action="store_true",
                        help="rejoue le test sur la rubrique fuitée du 15/08 (doit échouer)")
    parser.add_argument("--both", action="store_true", help="les deux, et vérifie le contraste")
    args = parser.parse_args(argv)

    if args.both:
        old = check(LEAKY_RUBRIC, label="15/08 — fuitée")
        print()
        new = check(_RUBRIC, label="16/08 — courante")
        print()
        if old == 0:
            print("ÉCHEC DU TEST LUI-MÊME : l'ancienne rubrique passe le contrôle.")
            return 1
        print("contraste vérifié : l'ancienne rubrique échoue, la courante passe."
              if new == 0 else "la rubrique courante échoue.")
        return new
    if args.old:
        return 0 if check(LEAKY_RUBRIC, label="15/08 — fuitée") else 1
    return check(_RUBRIC, label="16/08 — courante")


if __name__ == "__main__":
    raise SystemExit(main())
