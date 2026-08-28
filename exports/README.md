# WebVoyager-Verified v0.1

**Date de la mesure : 2026-08-15** · benchmark d'origine : WebVoyager (MinorJerry/WebVoyager @ 0915445, 2024-03-02) · produit par
`benchmark-doctor` (0.1.0), script `run_all.py --phase export`.

Un fichier : `webvoyager_verified_v0.1.jsonl`, **643 lignes** — une par tâche de
WebVoyager, dans l'ordre du corpus d'origine. Les statistiques agrégées sont dans
`webvoyager_verified_v0.1.stats.json`.

## Ce que ce fichier est

Une **réconciliation datée** de six audits publics indépendants de WebVoyager, augmentée
de métadonnées de stabilité mesurées le 2026-08-15. Chaque ligne porte :

| Champ | Contenu |
|---|---|
| `statut` | la recommandation d'usage (voir plus bas) |
| `verdict_consensuel` | `keep` / `modify` / `remove` / `conflit`, majorité des 6 annotateurs |
| `accord` | qui a signalé la tâche, combien, avec quelle action, et s'il y a désaccord dur |
| `stabilite` | score task-side, note A–D, catégorie dominante et **l'explication du calcul** |
| `taxonomie` | catégorie T1–T8 du défaut, pour les 121 tâches dont un patch-set motive le retrait |
| `patch_canonique` | l'énoncé corrigé retenu, sa source, sa date, ses variantes concurrentes, et s'il est **lui-même déjà périmé** |
| `enonce_perime` | si l'énoncé d'origine porte une date **déjà révolue** à la date de mesure, lesquelles, et si la tâche reste lançable sans retouche |
| `raisons_publiees` | les motifs bruts des annotateurs, tels qu'ils les ont écrits |

### Les cinq statuts

| Statut | n | Définition | Usage recommandé |
|---|---:|---|---|
| `noyau` | 474 | aucun des 6 annotateurs ne l'a jamais signalée | à exécuter |
| `surveiller` | 26 | consensus « conserver », mais au moins un annotateur l'a signalée | à exécuter, et à re-mesurer |
| `corriger` | 63 | consensus « réécrire » | à exécuter avec `patch_canonique` |
| `retirer` | 9 | consensus « supprimer » | à exclure du score |
| `conteste` | 71 | supprimée par au moins un annotateur ET conservée intacte par au moins un autre | **à ne pas trancher automatiquement** |

### Le sous-ensemble exécutable : deux chiffres, pas un

Le sous-ensemble consensuel (`noyau` ∪ `surveiller` ∪ `corriger`) compte
**563 tâches**. Ce n'est **pas** le nombre de tâches
lançables : le statut vient du vote des praticiens, pas de l'état de l'énoncé. À la date
de mesure, **84 de ces 563 énoncés
(14.9 %) portent une date déjà révolue** — dont
14 dans le `noyau`, c'est-à-dire parmi les tâches
que personne n'a jamais signalées. Sur ces 84,
13 disposent d'un patch canonique **lui-même périmé** et
14 n'ont aucun patch publié.

**Il y a donc trois chiffres, et il faut dire lequel on cite :**

| Lecture | n | Définition |
|---|---:|---|
| sous-ensemble consensuel | 563 | les praticiens ne demandent ni retrait ni arbitrage |
| **énoncé d'origine encore sain** | **479** | et l'énoncé ne porte aucune date révolue au 2026-08-15 |
| lançable après patch valide | 536 | ou un patch canonique non périmé le répare |

Le chiffre de référence est **479** : c'est le seul qui ne
suppose rien du travail d'autrui. Les 536 supposent en
plus que le patch d'un annotateur tiers est bon — or 20 des
116 patches recopiés ici sont eux-mêmes déjà périmés.

Aucune ligne n'est retirée du fichier pour autant. La péremption est **marquée**, dans le
champ `enonce_perime` de chaque ligne, avec les dates fautives et la date d'évaluation.
Trois raisons : le fichier est une photographie à 643 lignes — une par tâche —
et retirer des lignes casserait l'invariant qui le rend comparable dans le temps ; la
péremption est **datée**, elle sera vraie de plus de tâches dans six mois, et un champ se
recalcule là où une suppression est irréversible ; et c'est un résultat, pas un déchet.
Un utilisateur qui veut la liste courte l'obtient en une ligne :

```
jq -c 'select(.statut != "retirer" and .statut != "conteste"
       and .enonce_perime.executable_sans_retouche)' webvoyager_verified_v0.1.jsonl
```

Le statut `conteste` est le résultat, pas un déchet : 71 tâches sur
643 sont l'objet d'un désaccord dur entre praticiens. Aucun agrégat de
verdicts ne peut le résoudre ; il faudrait ouvrir le site et arbitrer à la main. C'est ce
que nous n'avons pas fait, et c'est écrit ici plutôt que masqué par un vote.

Le champ `patch_canonique` est renseigné dès qu'un annotateur a publié une réécriture,
**y compris sur des tâches de statut `retirer` ou `conteste`** : cela signale précisément
les tâches qu'un praticien a réparées là où un autre les a supprimées.

### Ce que l'outil en pense, statut par statut

Note de stabilité **détecteurs seuls** (sans l'a priori des praticiens, donc sans
circularité) croisée avec le statut issu du vote des praticiens :

| Statut \ Note | A | B | C | D |
|---|---:|---:|---:|---:|
| `noyau` | 201 | 121 | 123 | 29 |
| `surveiller` | 3 | 9 | 12 | 2 |
| `corriger` | 0 | 1 | 28 | 34 |
| `retirer` | 1 | 2 | 1 | 5 |
| `conteste` | 14 | 24 | 13 | 20 |

À lire dans les deux sens. 273 tâches que **personne** n'a jamais
signalées reçoivent une note inférieure à A, dont 29 en D ; et
1 tâche que les
praticiens veulent supprimer est notée A
par l'outil. L'outil et les praticiens ne signalent pas les mêmes tâches. Les tâches du noyau notées sous A sont, soit des faux positifs de l'outil (sondes d'accès propagées par site, ambiguïté jugée par un modèle), soit des défauts que personne n'a encore regardés. Rien dans ce fichier ne permet de trancher : il faudrait ouvrir le site.

## Ce que ce fichier n'est PAS

1. **Ce n'est pas un audit manuel des 643 tâches, et nous ne prétendons pas être les
   premiers.** Emergence AI a publié en mars 2026 un audit humain de WebVoyager et une
   version corrigée de **535 tâches templatées** (`EmergenceAI/EmergenceWebVoyager`).
   Microsoft Fara publie un sous-ensemble de 595 tâches, Convergence de 601, Alumnium de
   619, Skyvern de 635. Notre apport n'est ni l'audit ni la réparation : c'est la
   **réconciliation multi-annotateurs**, la **mesure longitudinale** et les
   **métadonnées de stabilité par tâche**, qui n'existent nulle part ailleurs.

2. **Ce n'est pas une réparation exhaustive du benchmark.** Aucune tâche n'a été
   ré-exécutée par un agent, aucun énoncé n'a été réécrit par nous. Les patches proposés
   sont ceux des annotateurs, recopiés et datés.

3. **Ce n'est pas un verdict de vérité.** Le champ `verdict_consensuel` est un décompte
   de majorité sur six sources qui n'ont ni le même but ni le même seuil : Magnitude
   re-date par précaution, Skyvern rafraîchit en masse, browser-use exclut. Une tâche
   « conservée » par une source peut simplement n'avoir jamais été examinée par elle —
   le silence y vaut conservation. L'accord publié est donc une **borne haute**.

4. **Ce n'est pas stable dans le temps — par construction, et ce n'est pas non plus un
   sous-ensemble propre.** 20 des
   116 patches recopiés ici sont **déjà périmés** à la date
   de la mesure : ils contiennent encore une date passée. Et surtout, l'énoncé d'origine
   lui-même est déjà révolu pour **84 des
   563 tâches du sous-ensemble consensuel
   (14.9 %)**. Le mot *Verified* de ce fichier porte sur
   la **réconciliation des verdicts** et sur la **datation des mesures** — jamais sur
   l'exécutabilité d'une tâche. Chaque ligne dit elle-même dans quel état elle est
   (`enonce_perime`) ; c'est le seul sens dans lequel ce fichier est vérifié.
   87 tâches reçoivent par ailleurs des correctifs textuellement
   différents selon l'annotateur. Un sous-ensemble « vérifié » est une photographie, pas
   un état.

5. **Ce n'est pas une mesure de la fiabilité des agents.** Le score de stabilité porte sur
   la *tâche* (mesure-t-elle encore ce qu'elle mesurait ?), pas sur l'agent (donne-t-il le
   même résultat d'un run à l'autre). Les deux se composent mais ne se confondent pas.

## Limites de mesure à connaître avant de citer un chiffre

- Les sondes réseau sont parties d'une **IP de datacenter**. Sur les trois sites bloqués
  que nous avons pu recouper avec un navigateur, deux répondaient normalement à
  celui-ci : les constats d'accès sont pondérés par une crédibilité de canal κ = 0,40 et
  ne doivent jamais être lus comme « tâche morte ».
- Les sondes ne portent que sur **l'URL de départ** de chaque tâche : WebVoyager n'en
  fournit pas d'autre. Le verdict d'accès d'un site est propagé à toutes ses tâches. Les
  taux bornent la décadence **par le bas**.
- Le score est **ordinal avant d'être cardinal**. Comparer deux tâches est légitime ; lire
  un score comme une probabilité ne l'est pas.

## Reproduire ce fichier

```
python3 run_all.py --phase audit     # mesure L1+L2+L3 sur les 643 tâches
python3 run_all.py --phase export    # ce fichier
python3 analysis_longitudinal.py     # les courbes de mortalité qui l'accompagnent
```

La base de verdicts réconciliée dont dérivent les champs `accord`, `taxonomie` et
`patch_canonique` se reconstruit par
`python3 -m benchmark_doctor.ground_truth.fetch_sources` puis `.reconcile`.

## Licence et citation

Le fichier dérive de corpus publics : WebVoyager (MIT, He et al. 2024) et des six
patch-sets cités, chacun sous sa propre licence. Les champs ajoutés par nous
(`statut`, `stabilite`, `taxonomie`, `accord`) sont publiés sous MIT.
