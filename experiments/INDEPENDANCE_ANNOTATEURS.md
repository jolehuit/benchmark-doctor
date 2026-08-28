# Indépendance des annotateurs — instruction du problème bloquant B3

**Date** : 16/08/2026 · **Objet** : `VERIFICATION.md` §B3 — « Convergence et Magnitude ne sont pas deux
annotateurs indépendants » · **Périmètre** : les 8 patch-sets de `data/raw/`, les dépôts distants
d'origine, les trois configurations d'accord inter-annotateurs, la courbe de mortalité A.

**Coût réel de cette instruction** : **0,01769 $** (champ `usage.cost` d'OpenRouter, 120 appels
`google/gemini-2.5-flash`, expérience §4.2). Tout le reste est hors ligne et déterministe.

---

## 0. Verdict en une page

Le **fait** avancé par le vérificateur est exact et je le reproduis au chiffre près : Convergence et
Magnitude partagent **56 de leurs 60 réécritures communes au caractère près (93,3 %)**.

**L'interprétation qu'il en tire — « deux votes pour un jugement », « une même lignée » — est fausse.**
Elle est réfutée par les sources primaires, que le vérificateur déclarait lui-même n'avoir pas
consultées (« *le sens de la filiation Convergence → Magnitude est déduit des dates du dépôt, non d'un
historique git consulté* », `VERIFICATION.md` §6). Je les ai consultées. Ce que j'y trouve :

1. Le fichier `data/patches.json` de Magnitude contient, pour chacune de ses 68 réécritures, un champ
   `prev` qui enregistre l'état de départ. **`prev` est égal à l'énoncé WebVoyager d'origine dans
   68 cas sur 68, et à l'énoncé de Convergence dans 0 cas sur 60.**
2. Le script `data/patch_tasks.py` du dépôt Magnitude **refuse d'appliquer un patch dont le `prev` ne
   correspond pas** au fichier d'entrée, et ce fichier d'entrée (`data/originalTasks.jsonl`) est
   **bit à bit identique au corpus WebVoyager d'origine** (md5 `35fc7219…`). La filiation depuis
   l'original est donc vérifiée par la machine, pas seulement déclarée.
3. Les mots `convergence`, `proxy-lite`, `2025Valid`, `WebVoyager2025` sont **absents de tout le dépôt
   Magnitude** (la seule occurrence de « convergence » est le terme mathématique dans l'énoncé de
   `Wolfram Alpha--36`). Le README ne cite que `MinorJerry/WebVoyager`.
4. **Une copie hérite des fautes de son modèle. Magnitude n'hérite d'aucune des trois fautes propres à
   Convergence** : la corruption `UNS A92024` → `UNS A92025` (une nuance d'aluminium prise pour une
   date), le `29 février 2026` (qui n'existe pas), et le `« today (February 17, 2026) »` autocontradictoire.
   Magnitude laisse la première intacte et corrige les deux autres de sa propre main.
5. Le 93 % n'est pas une empreinte de copie : c'est la **conséquence arithmétique** de deux chaînes de
   traitement mécaniques appliquant au même corpus la même règle (« décaler tous les millésimes ») avec
   la même constante (**+2 ans**). La constante est prédite par la date de l'artefact pour 5 des
   6 annotateurs (§4.1) ; Convergence et Magnitude tombent dans la même fenêtre.

**Ce qui reste vrai de B3, et qui doit être écrit dans le mémoire** : le mot « **indépendants** » doit
sauter, mais pour une raison plus large et mieux fondée que celle du vérificateur. Les six annotateurs
ne sont pas six tirages indépendants : ils héritent du **même corpus**, du **même défaut dominant**
(un millésime en dur, concentré dans les 44 tâches Booking et les 42 tâches Google Flights) et de la
**même réparation forcée**. Cette dépendance-là est structurelle et concerne **les six**, pas une paire.

**Configuration à retenir** : **les six voix brutes (κ = 0,737)**, publiée avec la bande de
sensibilité complète **κ ∈ [0,707 ; 0,737]** et la phrase de méthode du §7. Il n'y a aucune raison
factuelle de fusionner Convergence et Magnitude — et si l'on retenait le critère du vérificateur
(la proximité des verdicts), c'est **browser-use et Magnitude** qu'il faudrait fusionner d'abord
(§5, κ de Cohen 0,913 contre 0,857).

---

## 1. Ce qui a été établi aux sources primaires

Toutes les vérifications ci-dessous sont rejouables ; les commandes sont données au §9.

### 1.1 Convergence — dépôt HuggingFace `convergence-ai/WebVoyager2025Valid`

Dépôt cloné, historique git complet (5 commits, auteur unique *Fraser Greenlee*) :

| commit | date (UTC) | message |
|---|---|---|
| `db3e467` | 2025-02-17 14:31:57 | initial commit |
| `e219595` | 2025-02-17 14:37:35 | Upload test.csv |
| `3738dea` | 2025-02-17 14:39:05 | Upload test.csv |
| `0cff2d1` | 2025-02-17 14:44:10 | Create README.md |
| `9854e64` | 2025-02-25 11:39:17 | Update README.md |

`test.csv` **n'a plus bougé depuis le 17/02/2025** ; seul le README a été retouché le 25/02. Le fichier
téléchargé au commit épinglé est **bit à bit identique** à `data/raw/convergence_valid_20251220.csv`
(md5 `cff375ce…`). Le README ne cite qu'une source : *« You can find the original WebVoyager tasks
[here](https://github.com/MinorJerry/WebVoyager) »*. Magnitude n'existait pas encore.

**La chaîne de traitement de Convergence est mécanique**, et je le démontre sur les 601 lignes :

```
== original + « Use <url>. » au caractère près          : 531 / 601
== idem une fois les millésimes neutralisés             :  60 / 601
ni l'un ni l'autre                                      :  10 / 601
   dont 8 = ajout d'un point final avant « Use »
   dont 2 = vraie retouche : Wolfram Alpha--11 et Google Flights--9
```

Soit **591/601 (98,3 %) de l'énoncé d'origine mot pour mot hors millésime**. Convergence, c'est
WebVoyager + un suffixe d'URL + un décalage uniforme de millésimes. Deux tâches seulement reçoivent
un jugement éditorial, et l'une des deux est une faute (§1.3).

### 1.2 Magnitude — dépôt GitHub `magnitudedev/webvoyager`

Dépôt cloné. **5 commits, tous du 2025-07-06**, auteur unique *Anders Lie* ; `data/patches.json` est
introduit par le commit `init` (`8700931`). L'historique ne dit donc rien de la provenance — mais le
**contenu** du dépôt la dit entièrement :

| Artefact | Constat |
|---|---|
| `data/originalTasks.jsonl` | md5 `35fc7219…` = **identique** à `data/raw/webvoyager_original.jsonl` |
| `data/patches.json` | 121 entrées : 68 `{prev, new, reason}` + 53 `{remove, reason}` (md5 `fd44bac1…` = identique à notre copie) |
| champ `prev` vs énoncé **original** | **68 / 68 identiques** |
| champ `prev` vs énoncé **Convergence** | **0 / 60 identiques** |
| `data/patch_tasks.py` | applique le patch **seulement si** `task['ques'] == patch['prev']`, sinon `Warning: Task {id} doesn't match expected text` |
| mentions de Convergence / proxy-lite / 2025Valid | **aucune**, dans aucun fichier |

Le README de Magnitude documente la démarche sans ambiguïté : *« The original WebVoyager benchmark
contains many tasks which are time-dependent and thus outdated… we make patches to update dates on
several tasks, and remove a few impossible tasks as well. For details on exactly what changes we made
to the original tasks, see patches.json »*.

**Autrement dit : la chaîne de production de Magnitude est un `assert` sur le corpus d'origine.** Pour
qu'elle ait pu partir de Convergence, il aurait fallu que ses auteurs réécrivent après coup les
68 champs `prev` pour y remettre le texte original — c'est-à-dire fabriquer une preuve de provenance
dont personne ne leur demandait rien.

### 1.3 La preuve par les fautes non héritées

C'est le test décisif de filiation, et il est négatif dans les trois cas.

| Tâche | Original | Convergence (02/2025) | Magnitude (07/2025) |
|---|---|---|---|
| `Wolfram Alpha--11` | `UNS A9`**`2024`** | `UNS A9`**`2025`** — nuance d'aluminium corrompue par le décalage | **intacte** (jamais signalée) |
| `Booking--28` | `February 22 to February 29, 2024` | `February 22 to February 29, `**`2026`** — le 29/02/2026 n'existe pas | `February 21 to February 28, 2026` — **plage décalée d'un jour** |
| `Google Flights--1` | `one-way flights today (February 17, 2024)` | `today (February 17, `**`2026`**`)` — « aujourd'hui » + date fixe future | `on February 17, 2026` — **« today » supprimé** |

Une lignée propage ses erreurs. Ici, **zéro des trois défauts propres à Convergence n'apparaît chez
Magnitude**, et deux d'entre eux sont corrigés par une lecture que seul un annotateur regardant
l'énoncé original pouvait faire. Ce sont exactement les **4 tâches sur 60** où les deux textes
divergent : les deux ci-dessus, plus `Booking--34` et `Google Flights--33` où Convergence décale de
+1 an et Magnitude de +2.

---

## 2. Matrice de similarité des réécritures, caractère par caractère

Périmètre : pour chaque paire, les tâches que **les deux** ont réécrites (`action = modify` avec un
énoncé de remplacement). Trois lectures de la même matrice.

### 2.1 Lecture brute — celle du vérificateur (identité de chaîne)

| A | B | communes | identiques | % | similarité moyenne (difflib) |
|---|---|---:|---:|---:|---:|
| **convergence** | **magnitude** | **60** | **56** | **93,3 %** | 0,999 |
| magnitude | fara | 64 | 10 | 15,6 % | 0,966 |
| convergence | fara | 59 | 8 | 13,6 % | 0,963 |
| alumnium | skyvern_2026 | 69 | 5 | 7,2 % | 0,943 |
| browseruse | fara | 62 | 3 | 4,8 % | 0,959 |
| browseruse | convergence | 59 | 2 | 3,4 % | 0,991 |
| browseruse | magnitude | 63 | 2 | 3,2 % | 0,989 |
| magnitude | alumnium | 68 | 2 | 2,9 % | 0,963 |
| fara | alumnium | 73 | 2 | 2,7 % | 0,953 |
| convergence | alumnium | 60 | 1 | 1,7 % | 0,959 |
| fara | skyvern_2026 | 72 | 1 | 1,4 % | 0,953 |
| browseruse | alumnium | 63 | 0 | 0,0 % | 0,953 |
| browseruse | skyvern_2026 | 63 | 0 | 0,0 % | 0,966 |
| convergence | skyvern_2026 | 60 | 0 | 0,0 % | 0,968 |
| magnitude | skyvern_2026 | 66 | 0 | 0,0 % | 0,969 |

Le chiffre du vérificateur est reproduit exactement. **Mais la colonne « similarité moyenne » suffit
déjà à alerter : toutes les paires sont entre 0,943 et 0,999.** Deux réécritures quelconques du corpus
sont identiques à 95 % près, parce qu'elles sont toutes deux l'énoncé d'origine à quelques
caractères près.

Les sources hors accord se comportent de même (`skyvern_2025|skyvern_2026` : 12/20 = 60 % — deux
instantanés du **même** annotateur, ce que le dépôt sait déjà et neutralise).

### 2.2 Lecture contrôlée — en séparant réparation triviale et réparation de fond

Une « réécriture pur-millésime » est une réécriture dont le diff avec l'original ne touche **que** des
millésimes. C'est la réparation forcée : quand le seul défaut est une année en dur, le seul correctif
est de changer l'année.

| A | B | comm. | pur-millésime | ident. | % | de fond | ident. | % |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| convergence | magnitude | 60 | 58 | 56 | **96,6 %** | 2 | 0 | **0,0 %** |
| convergence | fara | 59 | 8 | 8 | **100,0 %** | 51 | 0 | 0,0 % |
| magnitude | fara | 64 | 10 | 8 | **80,0 %** | 54 | 2 | 3,7 % |
| alumnium | skyvern_2026 | 69 | 3 | 2 | 66,7 % | 66 | 3 | 4,5 % |
| browseruse | magnitude | 63 | 57 | 0 | 0,0 % | 6 | 2 | 33,3 % |
| browseruse | convergence | 59 | 58 | 2 | 3,4 % | 1 | 0 | 0,0 % |
| browseruse | skyvern_2026 | 63 | 32 | 0 | 0,0 % | 31 | 0 | 0,0 % |
| magnitude | skyvern_2026 | 66 | 32 | 0 | 0,0 % | 34 | 0 | 0,0 % |

**Convergence et Fara sont identiques à 100 % sur leur sous-ensemble contrôlé** (8/8). Personne ne
soutiendra que Microsoft a copié Convergence AI. C'est la réfutation par l'absurde du raisonnement de
B3 : l'identité sur les réparations triviales n'est pas un indice de filiation, c'est un indice que la
réparation est forcée.

Et sur les réécritures **de fond** — les seules où un jugement s'exerce — Convergence et Magnitude
s'accordent **0 fois sur 2**.

### 2.3 Lecture par neutralisation du millésime — « s'accordent-ils sur autre chose que l'année ? »

On remplace tout millésime par `<Y>` et on recompare.

| A | B | comm. | identité brute | identité **hors millésime** |
|---|---|---:|---:|---:|
| **browseruse** | **convergence** | 59 | 3,4 % | **98,3 %** |
| convergence | magnitude | 60 | 93,3 % | 96,7 % |
| browseruse | magnitude | 63 | 3,2 % | 93,7 % |
| convergence | skyvern_2026 | 60 | 0,0 % | 53,3 % |
| browseruse | skyvern_2026 | 63 | 0,0 % | 50,8 % |
| magnitude | skyvern_2026 | 66 | 0,0 % | 48,5 % |
| magnitude | alumnium | 68 | 2,9 % | 23,5 % |
| magnitude | fara | 64 | 15,6 % | 18,8 % |
| convergence | fara | 59 | 13,6 % | 13,6 % |
| alumnium | skyvern_2026 | 69 | 7,2 % | 8,7 % |

**La paire la plus « identique » du corpus n'est pas Convergence|Magnitude : c'est
browser-use|Convergence, à 98,3 %.** browser-use (12/2024) précède Convergence de deux mois et n'a
avec lui aucun lien. Toute la différence entre 98,3 % et 3,4 % d'identité brute tient à **un seul
entier** : browser-use décale de +1 an, Convergence de +2.

Conclusion des trois lectures : **la matrice ne mesure pas la dépendance entre annotateurs, elle
mesure le choix d'une constante de décalage.**

---

## 3. Recouvrement des décisions (et non des textes)

Deux tests supplémentaires, sur ce que les annotateurs **décident** plutôt que sur ce qu'ils écrivent.

**Suppressions — indice de Jaccard :**

| A | B | \|A\| | \|B\| | A∩B | Jaccard |
|---|---|---:|---:|---:|---:|
| **browseruse** | **magnitude** | 55 | 53 | 49 | **0,831** |
| browseruse | convergence | 55 | 42 | 40 | 0,702 |
| convergence | magnitude | 42 | 53 | 38 | 0,667 |
| browseruse | fara | 55 | 48 | 36 | 0,537 |
| magnitude | fara | 53 | 48 | 34 | 0,507 |
| magnitude | alumnium | 53 | 24 | 23 | 0,426 |
| … | … | | | | 0,042 – 0,386 |

**Choix des tâches à réécrire — indice de Jaccard :**

| A | B | \|A\| | \|B\| | A∩B | Jaccard |
|---|---|---:|---:|---:|---:|
| **browseruse** | **magnitude** | 66 | 68 | 63 | **0,887** |
| convergence | magnitude | 62 | 68 | 60 | 0,857 |
| browseruse | convergence | 66 | 62 | 59 | 0,855 |
| magnitude | alumnium | 68 | 85 | 68 | 0,800 |
| … | … | | | | 0,645 – 0,745 |

Sur les deux, **Convergence|Magnitude arrive derrière browser-use|Magnitude**. Si l'on cherchait une
paire redondante par le comportement, ce serait celle-là.

---

## 4. Pourquoi 93 % ne prouve rien : le mécanisme, mesuré

### 4.1 La constante de décalage est prédite par la date de l'artefact

Règle testée : *le plus petit `k ≥ 0` tel que la date décalée de `k` années soit strictement future à
la date de l'artefact*.

| annotateur | date | décalage majoritaire observé | prédit par la règle | concordance tâche à tâche |
|---|---|---:|---:|---:|
| browseruse | 2024-12-15 | **+1** (58/58) | +1 | 55/58 = 95 % |
| convergence | 2025-02-17 | **+2** (58/60) | +1 | 29/60 = 48 % |
| magnitude | 2025-07-06 | **+2** (58/60) | +2 | 58/60 = 97 % |
| fara | 2025-08-31 | **+2** (10/15) | +2 | 9/15 = 60 % |
| alumnium | 2026-03-17 | **+3** (11/17) | +3 | 13/17 = 76 % |
| skyvern_2026 | 2026-05-04 | **+3** (35/36) | +3 | 35/36 = 97 % |

Cinq annotateurs sur six suivent la règle du minimum. **Convergence est le seul à surcorriger d'un an**
— et son README dit pourquoi : le jeu est déclaré *« valid until 20th December 2025 »*, or son décalage
uniforme de +2 amène `Booking--8` (`20/12/2023`) exactement au **20/12/2025**. La date de péremption
annoncée par Convergence **est** la conséquence arithmétique de sa constante. Le choix est
auto-suffisant, documenté, et antérieur de cinq mois à Magnitude.

Magnitude, en juillet 2025, n'avait pas le choix : +1 ramenait les dates de janvier à juin 2025 dans le
passé. **+2 était pour lui le minimum viable.** Deux raisons différentes, un même entier — et à partir
de là, l'identité du texte est mécanique.

### 4.2 Contrôle empirique : un septième annotateur, indépendant par construction

J'ai fait réparer les **mêmes 60 tâches** par un LLM (`google/gemini-2.5-flash`, température 0) qui n'a
jamais vu aucun patch-set, en lui donnant seulement l'énoncé d'origine et une date de travail —
17/02/2025 (date de Convergence), puis 06/07/2025 (date de Magnitude). Coût : **0,01769 $**.

Décomposition de l'identité en ses deux facteurs :
**(A)** la réparation ne touche que le millésime · **(B)** le millésime choisi est le même, sachant (A).

| paire | (A) identité hors millésime | (B) même millésime sachant (A) | (A)×(B) = identité brute |
|---|---:|---:|---:|
| **Convergence 02/2025 \| Magnitude 07/2025** | 58/60 = **97 %** | 56/58 = **97 %** | 56/60 = **93 %** |
| LLM indép. @17/02/2025 \| Convergence | 44/60 = 73 % | 4/44 = 9 % | 4/60 = 7 % |
| LLM indép. @17/02/2025 \| Magnitude | 42/60 = 70 % | 2/42 = 5 % | 2/60 = 3 % |
| LLM indép. @06/07/2025 \| Convergence | 13/60 = 22 % | 10/13 = 77 % | 10/60 = 17 % |
| LLM indép. @06/07/2025 \| Magnitude | 13/60 = 22 % | 11/13 = 85 % | 11/60 = 18 % |

Millésimes retenus sur ces 60 tâches : Convergence `{+2 : 58, +1 : 2}` · Magnitude `{+2 : 60}` ·
LLM@02/2025 `{+1 : 56, +2 : 3}` · LLM@07/2025 `{+1 : 48, +2 : 11}`.

**Lecture honnête, y compris de ce qui ne m'arrange pas.** Cette expérience ne blanchit pas à elle
seule Convergence et Magnitude : un annotateur laissé libre ne reproduit pas 56/60. Elle établit deux
choses, et je m'en tiens là :

1. Le facteur (A) — « je ne touche que l'année » — est déjà à **70-73 %** chez un annotateur libre, et
   monte à **97 %** dès que la chaîne est scriptée. Or les §1.1 et §1.2 établissent que les deux
   chaînes **sont** scriptées : Convergence est l'original à 98,3 % hors millésime, Magnitude applique
   un `patch_tasks.py` qui vérifie l'original. Chez deux pipelines mécaniques, (A) vaut ~100 %.
2. Le facteur (B) — le millésime — est **le seul vrai degré de liberté**, et c'est un entier pris dans
   un ensemble à deux ou trois valeurs. Sa coïncidence est un événement ordinaire, pas une empreinte.

Une fois (A) fixé à ~1 par la nature des chaînes, l'identité brute observée n'est **rien d'autre** que
la coïncidence de (B). Le 93 % n'est donc pas une mesure de dépendance : c'est un thermomètre planté
dans un seul entier.

---

## 5. Les trois configurations d'accord inter-annotateurs (plus deux contrôles)

Règle de fusion : deux sources fusionnées comptent pour **une voix**, dont l'action est la **plus
sévère** des deux (`remove` > `modify` > `keep`). C'est la convention du vérificateur, et la plus
sévère des deux possibles.

| configuration | voix | κ Fleiss 3 cat. | κ Fleiss exclusion | κ Fleiss défaut | AC1 de Gwet | signalée_1 | signalée_3 | signalée par tous | supprimée_1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **A. six voix brutes** *(publiée)* | 6 | **0,7371** | **0,5136** | 0,7651 | 0,9046 | 169 | **123** | **68** | 78 |
| **B. Convergence + Magnitude fusionnés** | 5 | **0,7237** | **0,4682** | 0,7589 | 0,8971 | 169 | **119** | **73** | 78 |
| **C. Convergence exclu** | 5 | **0,7291** | **0,4718** | 0,7625 | 0,9000 | 166 | 118 | 73 | 76 |
| C′. Magnitude exclu *(contrôle symétrique)* | 5 | 0,7073 | 0,4350 | 0,7398 | 0,8951 | 167 | 113 | 68 | 75 |
| **D. browser-use + Magnitude fusionnés** *(contrôle)* | 5 | **0,7101** | **0,4292** | 0,7441 | 0,8945 | 169 | 115 | 70 | 78 |

Les valeurs de A et B reproduisent **exactement** celles du vérificateur (0,7371 → 0,7237 ;
0,5136 → 0,4682 ; signalée_3 123 → 119 ; « unanime » 68 → 73, en lisant « unanime » comme *signalée par
tous les annotateurs*).

**Matrice de Cohen sur les actions (les 643 tâches, 3 catégories) — la quantité qui alimente réellement
Fleiss :**

| paire | accord brut | κ de Cohen |
|---|---:|---:|
| **browseruse \| magnitude** | 0,9720 | **0,9133** |
| browseruse \| convergence | 0,9580 | 0,8619 |
| **convergence \| magnitude** | 0,9565 | **0,8567** |
| magnitude \| alumnium | 0,9331 | 0,7834 |
| browseruse \| fara | 0,9238 | 0,7740 |
| magnitude \| fara | 0,9238 | 0,7739 |
| fara \| alumnium | 0,9114 | 0,7248 |
| browseruse \| alumnium | 0,9129 | 0,7182 |
| convergence \| alumnium | 0,9176 | 0,7144 |
| convergence \| fara | 0,9036 | 0,6974 |
| alumnium \| skyvern_2026 | 0,9098 | 0,6758 |
| fara \| skyvern_2026 | 0,8896 | 0,6443 |
| magnitude \| skyvern_2026 | 0,8927 | 0,6389 |
| convergence \| skyvern_2026 | 0,8974 | 0,6286 |
| browseruse \| skyvern_2026 | 0,8865 | 0,6185 |

**Trois observations qui règlent la question de la configuration à retenir.**

1. Le κ de Fleiss porte sur les **actions**, pas sur le texte des réécritures. Le 93 % de B3 ne
   contamine donc pas directement le κ publié — il concerne un objet que le κ ne regarde pas.
2. Sur les actions, `convergence|magnitude` (κ = 0,857) est **la troisième paire**, derrière
   `browseruse|magnitude` (0,913). Le vérificateur écrit que « κ = 0,857 est une copie » : à ce compte,
   0,913 en serait une plus grosse encore. C'est la configuration D, et elle fait **plus** de dégâts
   (0,7101) que la fusion qu'il recommande (0,7237).
3. **Les cinq configurations tiennent dans une bande de 3 points : κ ∈ [0,707 ; 0,737]**, toutes
   qualifiées de *substantielles* au sens de Landis-Koch (0,61-0,80). Le résultat du mémoire est
   **robuste au choix de convention**, et c'est cela qu'il faut publier.

**Configuration retenue : A (six voix brutes, κ = 0,737)**, accompagnée obligatoirement de la bande
[0,707 ; 0,737] et de la réserve du §7. Aucun fait n'autorise à fusionner Convergence et Magnitude ; et
la seule fusion défendable par le comportement (D) serait `browser-use + Magnitude`, que rien
n'appuie non plus.

---

## 6. Courbe de mortalité A (cumul des tâches signalées)

Les +5 tâches de Convergence au 17/02/2025 sont-elles nouvelles ou héritées ? **Elles ne peuvent pas
être héritées : Convergence précède Magnitude de cinq mois** et son fichier n'a plus bougé depuis. La
seule question qui se pose est donc l'inverse — sont-elles *propres* à Convergence ou *retrouvées* par
d'autres ?

| tâche | verdict Convergence | signalée aussi par |
|---|---|---|
| `Booking--5` | modify | magnitude, fara, alumnium, skyvern_2026 (**5 voix sur 6**) |
| `ESPN--33` | remove | magnitude, fara, alumnium, skyvern_2026 (**5 voix sur 6**) |
| `BBC News--30` | remove | *personne* |
| `Google Flights--9` | modify | *personne* (ajout de « , 2026 » à une date sans millésime) |
| `Wolfram Alpha--11` | modify | *personne* — **faux positif** (`UNS A92024` n'est pas une date, §1.3) |

**Deux des cinq sont confirmées par quatre autres annotateurs**, une est un apport propre défendable
(`BBC News--30`), une est un apport propre discutable (`Google Flights--9`) et **une est une erreur**.
Aucune n'est héritée. Réciproquement, Magnitude apporte **7 tâches que Convergence n'avait pas vues**
(`Amazon--6`, `Apple--22`, `Apple--32`, `BBC News--29`, `GitHub--29`, `Google Search--6`,
`Google Search--39`) — ce qu'une copie ne ferait pas.

**Les trois lectures de la courbe :**

| date | jalon | signalées | nouvelles | cumul | % du corpus |
|---|---|---:|---:|---:|---:|
| *(A) six voix brutes — publiée* | | | | | |
| 2024-12-15 | browser-use | 121 | 121 | 121 | 18,8 % |
| 2025-02-17 | Convergence | 104 | **5** | 126 | 19,6 % |
| 2025-07-06 | Magnitude | 121 | **7** | 133 | 20,7 % |
| 2025-08-31 | Fara | 134 | 20 | 153 | 23,8 % |
| 2026-03-17 | Alumnium | 109 | 4 | 157 | 24,4 % |
| 2026-05-04 | Skyvern | 99 | 12 | 169 | **26,3 %** |
| *(B) lignée fusionnée en un jalon unique daté du 06/07/2025* | | | | | |
| 2024-12-15 | browser-use | 121 | 121 | 121 | 18,8 % |
| 2025-07-06 | Convergence+Magnitude | 126 | **12** | 133 | 20,7 % |
| 2025-08-31 | Fara | 134 | 20 | 153 | 23,8 % |
| 2026-03-17 | Alumnium | 109 | 4 | 157 | 24,4 % |
| 2026-05-04 | Skyvern | 99 | 12 | 169 | **26,3 %** |
| *(C) Convergence exclu* | | | | | |
| 2024-12-15 | browser-use | 121 | 121 | 121 | 18,8 % |
| 2025-07-06 | Magnitude | 121 | 9 | 130 | 20,2 % |
| 2025-08-31 | Fara | 134 | 20 | 150 | 23,3 % |
| 2026-03-17 | Alumnium | 109 | 4 | 154 | 24,0 % |
| 2026-05-04 | Skyvern | 99 | 12 | 166 | **25,8 %** |

**La courbe est insensible à la question.** Le point d'arrivée passe de 169 (26,3 %) à 169 (26,3 %) en
fusionnant, et à 166 (25,8 %) en excluant Convergence : **un demi-point sur deux ans**. Fusionner ne
change **aucune** valeur du cumul — la fusion modifie le nombre de *voix*, pas l'ensemble des tâches
vues ; elle ne fait que supprimer un point d'observation daté (17/02/2025) et reporter ses 5 tâches sur
le jalon suivant. **Rien dans la courbe A ne dépend de l'issue de B3.**

---

## 7. Fragilité à marquer explicitement — base d'étiquetage de la taxonomie

*(point 4 de la mission ; signalé par `VERIFICATION.md` §6, non corrigé ailleurs)*

La table « **rappel par catégorie** » du rapport 6 (`runs/validation_ablation_20260815.json`,
clé `par_categorie`) et la ventilation de la taxonomie reposent **intégralement** sur
`benchmark_doctor/ground_truth/magnitude_reason_labels.json` : la relecture manuelle des
**121 raisons publiées par Magnitude**. Quatre réserves, à faire figurer dans le mémoire :

1. **Source unique.** Ces 121 étiquettes viennent d'**un seul** des sept patch-sets. Les six autres ne
   publient aucune raison exploitable (browser-use : « aucune raison documentée » ; Fara : idem ;
   Convergence : aucune ; Skyvern : un nom de fichier ; Alumnium : 20 messages de commit reconstitués).
   L'instruction de B3 ne change rien à ce point — Magnitude est bien un annotateur indépendant (§1) —
   mais la base d'étiquetage reste **mono-source**.
2. **Annotateur unique, sans second codeur.** L'étiquetage est le fait d'un seul agent. **Il n'existe
   aucun κ inter-annotateurs sur la taxonomie elle-même**, donc aucune mesure de la reproductibilité du
   codage. 16 cas frontaliers sont signalés par l'annotateur, ce qui est honnête mais ne remplace pas
   un second codeur. C'est la limite la plus attaquable en soutenance sur le chapitre 2.
3. **Effectifs minuscules sur la moitié des lignes.** Répartition réelle des 121 étiquettes :

   | catégorie | T1 | T2 | T3 | T4 | T5 | T8 | T6, T7 |
   |---|---:|---:|---:|---:|---:|---:|---:|
   | effectif | 70 | 21 | 11 | **7** | **5** | **7** | **0** |

   **Trois lignes sur six de la table de rappel reposent sur 19 étiquettes au total, et les deux plus
   petites (T5 et T4) sur 12.** Un rappel affiché sur `n = 5` a un intervalle de confiance à 95 % qui
   couvre presque tout l'intervalle [0 ; 1] : ces lignes ne sont pas des mesures, ce sont des
   indications. **T6 et T7 n'ont aucune étiquette** — la table n'a donc pas de ligne T7, alors que T7
   est la deuxième catégorie du tableau de « prévalence » (cf. `VERIFICATION.md` §C5).
4. **Formulation imposée pour le mémoire** : *« Le rappel par catégorie est mesuré contre les
   121 raisons publiées par un seul des sept patch-sets, relues et codées par un annotateur unique sans
   second codeur, donc sans accord inter-codeurs mesurable. Trois des six catégories renseignées
   reposent sur moins de dix cas (T4 : 7, T5 : 5, T8 : 7) et deux catégories de la taxonomie (T6, T7)
   n'y apparaissent pas faute d'une seule étiquette. Ces lignes sont données à titre indicatif et ne
   supportent aucune comparaison statistique. »*

---

## 8. Ce qu'il faut écrire dans le mémoire

**8.1 — Remplacer le mot « indépendants » partout**, y compris dans le champ `"description"` de
`runs/validation_ablation_20260815.json` (« *signalée … par au moins 1 des 6 annotateurs indépendants* »)
et dans le README. Non pas parce que deux annotateurs seraient une copie, mais parce qu'aucun des six
ne l'est au sens statistique.

**8.2 — Phrase de méthode (chapitre 4, section corpus)**, à recopier telle quelle :

> Nous parlons de **six patch-sets** et non de six annotateurs indépendants. Les six observent le même
> corpus, y rencontrent le même défaut dominant — un millésime écrit en dur, concentré dans les
> 44 tâches Booking et les 42 tâches Google Flights — et n'ont, pour le réparer, qu'un seul geste
> possible : décaler l'année. Deux d'entre
> eux, Convergence (02/2025) et Magnitude (07/2025), retiennent le même décalage de deux ans et
> produisent de ce fait 56 de leurs 60 réécritures communes identiques au caractère près. Nous avons
> vérifié aux sources primaires qu'il ne s'agit pas d'une filiation : le fichier `patches.json` de
> Magnitude enregistre pour chacun de ses 68 correctifs l'énoncé de départ, lequel est celui du corpus
> d'origine dans 68 cas sur 68 et celui de Convergence dans aucun ; son script d'application refuse tout
> patch qui ne s'applique pas au corpus d'origine ; et Magnitude n'hérite d'aucune des trois erreurs
> propres à Convergence, dont il corrige deux de sa propre main. L'hypothèse d'indépendance des six
> voix reste néanmoins violée pour une raison structurelle qui les concerne toutes ; nous publions donc
> le κ de Fleiss avec sa bande de sensibilité, **0,71 à 0,74 selon la convention de comptage des voix**,
> et retenons 0,737 (six voix) comme valeur de référence.

**8.3 — Ne jamais écrire** « Convergence et Magnitude sont deux jalons d'une même lignée » (formulation
proposée par le vérificateur) : c'est démenti par les sources primaires. Écrire à la place « deux
chaînes de réparation mécaniques qui retiennent le même décalage ».

**8.4 — Résultat gratuit à ajouter**, parce qu'il est solide et qu'il sert la thèse : *« Le correctif
appliqué à une tâche périmée est à ce point contraint que deux équipes sans lien produisent le même
texte au caractère près dans 93 % des cas — dès lors qu'elles choisissent le même décalage d'années.
Le désaccord entre patch-sets ne porte donc pas sur la réparation, il porte sur son millésime, c'est-
à-dire sur la durée de vie que chacun accorde au benchmark : +1 an pour browser-use, +2 pour
Convergence et Magnitude, +3 pour Alumnium et Skyvern. C'est exactement ce qu'un score de stabilité
daté cherche à rendre explicite. »*

**8.5 — Corriger la table du rapport 2** : le κ pairé `convergence|magnitude` = 0,857 doit rester
publié comme un accord ; le κ le plus élevé du corpus est `browseruse|magnitude` = 0,913, et il faut
le dire, car il est plus surprenant et il est réel.

---

## 9. Reproduction

Toutes les mesures hors ligne se rejouent depuis `data/raw/` sans accès réseau ni clé d'API.

```bash
# --- vérification des sources distantes (réseau requis) --------------------------------
curl -s "https://huggingface.co/api/datasets/convergence-ai/WebVoyager2025Valid/commits/main"
git clone https://huggingface.co/datasets/convergence-ai/WebVoyager2025Valid /tmp/conv
curl -sL "https://huggingface.co/datasets/convergence-ai/WebVoyager2025Valid/resolve/\
9854e641831b59d5090891830d129f07f54d2219/test.csv" | md5sum   # cff375ce72673fb2cd931a8a93d644a1

git clone https://github.com/magnitudedev/webvoyager /tmp/mag
git -C /tmp/mag log --format='%h|%ad|%an|%s' --date=iso        # 5 commits, tous du 2025-07-06
md5sum /tmp/mag/data/originalTasks.jsonl data/raw/webvoyager_original.jsonl   # identiques
grep -ril "proxy-lite\|2025Valid\|WebVoyager2025" /tmp/mag     # aucun résultat
```

```python
# --- filiation : le champ prev de Magnitude ---------------------------------------------
import json
pat = json.load(open("data/raw/magnitude_patches.json"))
orig = {json.loads(l)["id"]: json.loads(l)["ques"]
        for l in open("data/raw/webvoyager_original.jsonl")}
n = sum(1 for k, v in pat.items() if "prev" in v)
eq = sum(1 for k, v in pat.items() if v.get("prev", "").strip() == orig[k].strip())
print(eq, "/", n)          # -> 68 / 68
```

```python
# --- matrice de similarité et trois configurations d'accord -----------------------------
import itertools, re
from benchmark_doctor.ground_truth import loaders, sources
from benchmark_doctor.ground_truth.stats import fleiss_kappa, cohen_kappa, ACTIONS

original, per_source, _ = loaders.load_all(None)
ids = list(original)
ann = [s.key for s in sources.annotator_sources()]
YR = re.compile(r"\b(?:19|20)\d{2}\b")
mods = lambda k: {t: per_source[k][t].new_question for t in ids
                  if per_source[k][t].action == "modify" and per_source[k][t].new_question}
M = {k: mods(k) for k in ann}
for a, b in itertools.combinations(ann, 2):
    c = sorted(set(M[a]) & set(M[b]))
    ex = sum(1 for t in c if M[a][t] == M[b][t])
    mk = sum(1 for t in c if YR.sub("<Y>", M[a][t]) == YR.sub("<Y>", M[b][t]))
    print(f"{a:13s}{b:13s} {len(c):3d} brut {ex:3d} hors-millésime {mk:3d}")

SEV = {"keep": 0, "modify": 1, "remove": 2}; INV = {v: k for k, v in SEV.items()}
def kappa(groups):                       # groups = liste de listes de clés (1 groupe = 1 voix)
    R = [[INV[max(SEV[per_source[k][t].action] for k in g)] for g in groups] for t in ids]
    return fleiss_kappa(R, ACTIONS)["kappa"]
print(kappa([[k] for k in ann]))                                                   # 0.7371
print(kappa([[k] for k in ann if k not in ("convergence","magnitude")]
            + [["convergence","magnitude"]]))                                      # 0.7237
print(kappa([[k] for k in ann if k != "convergence"]))                             # 0.7291
print(kappa([[k] for k in ann if k not in ("browseruse","magnitude")]
            + [["browseruse","magnitude"]]))                                       # 0.7101
```

L'expérience du §4.2 (seule dépense) appelle `google/gemini-2.5-flash` à température 0 sur les
60 énoncés d'origine, avec pour seule consigne la date de travail et « change as little as possible ».
Coût mesuré par `usage.cost` : **0,01769 $** pour 120 appels.

---

## 10. Angles morts de cette instruction

Par symétrie avec la méthode du vérificateur, voici ce que je **n'ai pas** pu établir.

- **L'historique de Magnitude est écrasé.** Le dépôt ne compte que 5 commits, tous du 06/07/2025, et
  `patches.json` arrive dans le commit `init`. Je ne peux donc **pas** observer la fabrication des
  patches ; toute ma démonstration repose sur la cohérence interne de l'artefact livré (`prev` = original
  en 68/68, `patch_tasks.py` qui l'assert, fautes non héritées). C'est une preuve forte mais indirecte :
  un acteur déterminé à masquer un emprunt aurait pu reconstruire les `prev`. Rien ne l'indique, et il
  n'aurait eu aucun motif de le faire, mais je ne peux pas l'exclure formellement.
- **Je n'ai trouvé aucune mention explicite d'emprunt, ni dans un sens ni dans l'autre**, ni dans les
  README, ni dans les messages de commit, ni dans le code. L'absence de mention n'est pas une preuve
  d'absence d'emprunt ; elle est cohérente avec tout le reste.
- **Je n'ai pas cherché de source commune tierce** (un billet, un gist, un fil de discussion) dont les
  deux équipes auraient pu partir. La règle « +2 ans » est trop banale pour qu'une telle source soit
  nécessaire, mais je ne l'ai pas cherchée.
- **L'expérience du §4.2 mesure un annotateur libre, pas un pipeline scripté.** Elle ne reproduit donc
  pas le régime de Convergence et Magnitude et ne peut pas, seule, servir de preuve de non-copie
  (cf. la lecture honnête au §4.2). Elle sert à décomposer le 93 %, pas à l'excuser.
- **La convention de fusion retenue est « action la plus sévère »** (celle du vérificateur). Une fusion
  par vote majoritaire ou par action la plus clémente donnerait des κ légèrement différents ; je ne les
  ai pas calculés, la question étant devenue sans objet.
- **Je n'ai rien vérifié du contenu réel des sites** : la question de savoir si `BBC News--30` ou
  `Google Flights--9` étaient effectivement cassées en février 2025 reste ouverte, comme partout
  ailleurs dans ce dossier.
