# Chiffres canoniques du mémoire

**Établi le 16/08/2026** · périmètre : les chiffres que le mémoire de M2 MIAGE va porter sur
`benchmark-doctor` et WebVoyager · en réponse à `VERIFICATION.md` §C8 et §C9.

> **Ce fichier est la seule source chiffrée autorisée pour les rédacteurs**, comme la
> bibliographie vérifiée l'est pour les sources. Un chiffre qui n'est pas ici n'entre pas
> dans le mémoire. Un chiffre qui est ici entre avec **la réserve écrite en face** — la
> réserve fait partie du chiffre, elle n'est pas un commentaire optionnel.

Chaque ligne porte : la valeur, la commande qui la reproduit, le fichier qui en fait foi.
Le registre entier se contrôle en une seconde, hors ligne et à coût nul :

```
python3 experiments/verifier_chiffres.py     # 70 chiffres relus dans 12 fichiers source
```

Ce contrôle **relit les artefacts** ; il ne recalcule rien. Il échoue si un chiffre de ce
document cesse de correspondre à son fichier. Il a été exécuté avant la publication de
cette version : **70 OK, 0 écart**.

---

## 0. La configuration canonique, en toutes lettres

Trois cartes de santé circulaient. Elles ne se contredisaient pas — c'étaient trois
configurations du même outil — mais aucune n'était déclarée comme la référence, si bien que
le README publiait une carte pendant que les tables de sensibilité en publiaient une autre.
**Une seule est désormais citable :**

| Paramètre | Valeur canonique |
|---|---|
| Corpus | `data/raw/webvoyager_original.jsonl`, 643 tâches, sha256 `69b19fd8…c488` |
| Date de référence | **2026-08-15**, gelée (`run_all.REFERENCE_DATE`) |
| Couches actives | **L1 + L2 + L3**, couche de solvabilité **incluse** |
| Canal L2 | `direct_http:browser` — `http_datacenter`, κ = 0,40 **face au juge navigateur-datacenter** (κ ne se lit pas sans son juge, cf. §12.4) |
| Extrait classifié L2 | **3 000 caractères** — paramètre de mesure à publier, cf. §12.8 |
| Contenus L2 | vérifiés (`--l2-content`) |
| Modèle de juge L3 | **`google/gemini-2.5-flash`**, rubrique, **seuil 0,5** |
| Solvabilité L3 | `google/gemini-2.5-flash` |
| A priori praticiens | `data/ground_truth.json`, inclus dans le score publié |
| Échelle de notes | **A > 0,75 · B > 0,50 · C > 0,25 · D ≤ 0,25** (unique depuis le 16/08) |
| Carte de référence | **`runs/health_20260815.json`** |

Elle se rejoue **hors ligne, sans un appel réseau et sans un centime**, depuis le journal de
constats gelé — et le rejeu reproduit la carte publiée à l'identique :

```
python3 experiments/carte_canonique.py --check
#  notes : {'A': 210, 'B': 138, 'C': 185, 'D': 110}   stabilité : 0.5851
#  contrôle contre la carte publiée : IDENTIQUE
```

L'inventaire des autres cartes, avec la raison de leur mise à l'écart, est dans
**`runs/CARTES.md`**. Chaque JSON porte en tête un champ `statut_editorial`.

### Le piège nommément

Ne **jamais** écrire dans le même paragraphe « stabilité moyenne 0,585 » (carte canonique) et
« κ = 1 → 144 tâches en note D » (table du rapport 5) : la seconde est calculée **sans la
couche de solvabilité**. Dans la configuration canonique, κ = 1 donne **177**.

---

## 1. La carte de santé canonique

| # | Affirmation | Chiffre canonique | Réserve obligatoire |
|---|---|---|---|
| 1.1 | Corpus audité | **643 tâches**, sha256 `69b19fd8…c488` | l'empreinte est celle du commit épinglé, re-téléchargeable |
| 1.2 | Stabilité moyenne task-side | **0,585** (détecteurs seuls **0,612**) | score **ordinal**, pas une probabilité ; il intègre l'a priori des praticiens |
| 1.3 | Distribution des notes | **A 210 · B 138 · C 185 · D 110** | l'échelle est celle de la ligne « échelle de notes » du §0, et d'aucune autre |
| 1.4 | Part du corpus sous la note A | **67,3 %** | dont une part de faux positifs non quantifiée (cf. §8) |
| 1.5 | Coût de la campagne | **0,263 $** pour 643 tâches, soit **0,00041 $/tâche** | coût d'une **première** exécution ; les relectures sont servies par `runs/l3_cache` à 0 $ |
| 1.6 | Crédibilité du canal | **κ = 0,40** | **repose sur n = 3 URL**, dont une seule « confirmée », et cette confirmation est contestable (cf. §2.2). **Réestimé le 16/08 sur un plan croisé complet, cf. §12.4 : la valeur tient, sa lecture change (κ appartient à un COUPLE), et la confirmation qui la portait est infirmée.** |
| 1.7 | Échelle de notes | **A > 0,75 · B > 0,50 · C > 0,25 · D ≤ 0,25** | chaque frontière vaut 1 − w(σ) ; comparaison **stricte** (la frontière appartient à la note inférieure) ; **aucun seuil n'est ajusté sur la vérité terrain**, qui sert déjà à l'évaluation |
| 1.8 | Sous-ensembles les plus atteints | **Booking 44/44 sous A dont 33 en D**, **Google Flights 42/42 sous A** | verdict d'accès mesuré sur l'URL de départ puis propagé au site |

**Commande** : `python3 run_all.py --phase audit --l3-backend llm`
**Fait foi** : `runs/health_20260815.json` (champs `summary`, `by_site`, `cost`, `scoring_model`)

---

## 2. Sensibilité du score — **dans la configuration canonique**

Ces tables remplacent celles du rapport 5, qui étaient calculées sans la couche de
solvabilité et ne se mélangent donc pas à la carte du README.

### 2.1 — Le rejeu hors ligne reproduit la carte publiée

Contrôle `identique = true`. **Fait foi** : `runs/carte_canonique_20260815.json`, champ
`controle_de_rejeu`.

### 2.2 — Sensibilité à κ

| κ | stabilité ⌀ | A | B | C | **D** |
|---:|---:|---:|---:|---:|---:|
| 0,00 | 0,6240 | 251 | 120 | 189 | **83** |
| 0,20 | 0,6048 | 251 | 117 | 175 | **100** |
| **0,40 (retenu)** | **0,5851** | **210** | **138** | **185** | **110** |
| 0,60 | 0,5652 | 210 | 119 | 201 | **113** |
| 0,80 | 0,5450 | 210 | 75 | 222 | **136** |
| 1,00 | 0,5248 | 210 | 75 | 181 | **177** |

**Réserve obligatoire, et elle est inconfortable.** Un κ plus grand produit **plus** de tâches
mortes. Le choix de κ = 0,40 plutôt que κ = 0,20 fait donc passer de 100 à 110 tâches en D :
il va **dans le sens de la thèse du mémoire**. La formulation « lecture la plus prudente pour
le score » est fausse et doit disparaître. Formulation à employer : *« nous retenons la
lecture la plus défavorable au site, donc celle qui gonfle le plus notre propre mesure de
décadence ; la table de sensibilité (83 → 177 tâches en D) borne l'effet de ce choix, qui
repose sur n = 3 observations non reproductibles. »*

### 2.3 — Sensibilité à l'agrégation

**510 tâches (79,3 %) portent plus d'une catégorie** ; passer de l'OU bruité au maximum
change **122 notes sur 643**. (Le rapport 5 annonçait 262 et 83 : c'était sans la solvabilité.)

### 2.4 — Ce qu'aurait donné l'échelle abandonnée

Sur la même carte, l'échelle héritée 0,85 / 0,60 / 0,35 donnait **A 193 · B 124 · C 146 ·
D 180**. À ne citer que pour rendre lisibles les rapports antérieurs au 16/08.

**Commande** : `python3 experiments/carte_canonique.py`
**Fait foi** : `runs/carte_canonique_20260815.json`

---

## 3. La couche L1 (statique)

| # | Affirmation | Chiffre canonique | Réserve obligatoire |
|---|---|---|---|
| 3.1 | Tâches signalées au seuil HIGH | **73 / 643 (11,3 %)** | — |
| 3.2 | Notes de la carte L1 seule | **A 509 · B 61 · C 73 · D 0** | **a changé** : l'ancienne échelle donnait D 65. Aucun détecteur statique n'annonce une confiance de 1,0, donc aucun ne peut atteindre D. **Ne plus écrire « 65 tâches mortes au seul examen statique ».** |
| 3.3 | Précision / rappel contre `signalee_1` | **P 0,986 · R 0,426** | **in-sample** : 71 des 72 vrais positifs sont des tâches Magnitude, le patch-set qui a servi à régler les détecteurs. À ne jamais citer sans la ligne 4.1. |
| 3.4 | Précision contre `supprimee_1` | **P 0,164**, hasard 0,121, **lift 1,36**, p = 0,17 | **résultat nul.** Voir la nuance ci-dessous : elle nous est défavorable et doit être dite telle quelle. |
| 3.5 | Rappel de la campagne complète (MEDIUM) | **R 0,894** | obtenu en signalant **424 tâches sur 643 (66 %)** ; un tirage au hasard de 424 tâches obtiendrait déjà 0,66. Le lift réel est de 1,35. **Ne jamais citer 0,89 sans le dénominateur.** |

### 3.6 — La colonne `supprimee_1`, au chiffre près

`supprimee_1` (« supprimée par au moins un praticien ») est la vérité la plus proche de
« la tâche est morte », et c'est là que l'outil est le plus faible. Test binomial unilatéral
contre la prévalence 0,121 (78/643), recalculé et reproduit :

| Configuration | seuil | signalées | VP | P | lift | p unilatéral |
|---|---|---:|---:|---:|---:|---:|
| L1 | high | 73 | 12 | 0,164 | 1,36 | 0,170 |
| L1+L2 | high | 214 | 32 | 0,150 | 1,23 | 0,125 |
| L1+L2+L3 | high | 274 | 45 | 0,164 | **1,35** | **0,022** |
| L1+L2+L3 | medium | 424 | 63 | 0,149 | 1,22 | 0,053 |

**Correction d'une formulation trop généreuse envers nous, et d'une trop sévère.** Le
vérificateur écrit qu'*aucune* configuration au seuil HIGH n'est significative contre
`supprimee_1` ; c'est inexact — la campagne complète y atteint p = 0,022. Mais cette
p-valeur ne survit pas au contrôle de multiplicité : la grille compte 8 configurations
× 5 vérités = 40 tests, et le seuil de Bonferroni est 0,00125. **La conclusion du
vérificateur tient donc, mais pour une autre raison que celle qu'il donne**, et c'est
celle-là qu'il faut écrire : *« contre la vérité “supprimée par un praticien”, le meilleur
lift de la grille est 1,35 et aucune p-valeur ne survit à la correction de multiplicité.
Nos détecteurs voient ce qui se périme, pas ce que les praticiens décident de retirer. »*

**Commandes** :
`python3 -m benchmark_doctor.cli scan data/raw/webvoyager_original.jsonl --today 2026-08-15`
`python3 run_all.py --phase validate`
`python3 experiments/verifier_chiffres.py` (recalcule les p-valeurs du tableau 3.6)
**Fait foi** : `runs/health_webvoyager_20260815.json`, `runs/validation_ablation_20260815.json`

---

## 4. Validation hors échantillon (correction du bloquant B2)

| # | Affirmation | Chiffre canonique | Réserve obligatoire |
|---|---|---|---|
| 4.1 | L1 au seuil HIGH, hors du patch-set d'ajustement | **non validable** — 2 tâches signalées sur 522 | le test n'est pas sans puissance : un 2/2 parfait aurait donné p = 0,0085. C'est le détecteur qui est muet. |
| 4.2 | L1 au seuil MEDIUM, hors échantillon | **tient** — P 0,327 contre 0,092 au hasard, lift 3,55, p = 4,5·10⁻⁶ (p stratifiée intra-site 0,0036) | **c'est le résultat de référence du mémoire pour L1**, pas le 0,986 |

**Commande** : `python3 experiments/validation_hors_echantillon.py`
**Fait foi** : `runs/validation_hors_echantillon_20260816.json`, champ `conclusions`

---

## 5. Accord entre annotateurs

| # | Affirmation | Chiffre canonique | Réserve obligatoire |
|---|---|---|---|
| 5.1 | Tâches signalées par au moins un des six | **169 / 643** ; par les six : **68** ; jamais signalées : **474** | « le silence vaut conservation » : une source qui n'examine pas une tâche est comptée comme la conservant. Tous les cumuls sont des **bornes basses**. |
| 5.2 | Fleiss κ, 3 catégories | **0,737** (exclusion seule : **0,514**) | les six sont six **patch-sets**, pas six annotateurs humains indépendants. Voir `experiments/INDEPENDANCE_ANNOTATEURS.md` pour l'instruction complète de la contestation B3. |
| 5.3 | Divergence des correctifs | **87 tâches réécrites par ≥ 2 sources ; 76 (87,4 %) divergent sur le millésime ; 4,0 variantes distinctes pour 4,9 réécritures** | **ne pas écrire « 100 % des correctifs divergent »** : la formulation exacte est *« aucune des 87 tâches ne reçoit un correctif unanime »*. La mesure à mettre en avant est **76/87 = 87,4 %**, qui est robuste. |

**Commande** : `python3 -m benchmark_doctor.ground_truth.reconcile`
**Fait foi** : `data/ground_truth.json`, champ `statistiques`

---

## 6. Mesure longitudinale

| # | Affirmation | Chiffre canonique | Réserve obligatoire |
|---|---|---|---|
| 6.1 | **Les correctifs pourrissent** | **65 des 65 réécritures datées de Magnitude sont déjà périmées en 13,3 mois ; 0 conserve une date future** | résultat reproduit indépendamment par le vérificateur. **C'est le résultat le plus solide du dossier.** |
| 6.2 | Taux de décadence à citer | **6,7 %/an** [IC 95 % : 5,1 – 8,8 %] — 48 des 522 tâches jugées saines en 12/2024 signalées ensuite | seul estimateur non censuré à gauche ; il ne voit que ce que des auditeurs bénévoles ont regardé, donc il **sous-estime** |
| 6.3 | Dénominateur browser-use | **588 tâches** (643 − 55 exclusions déclarées) | le chiffre « 1,9 % de flags à sa naissance » était calculé sur 643 : le vrai est **0,5 %** |
| 6.4 | Contrôle Online-Mind2Web | **52 tâches distinctes remplacées** sur 300 en 13,3 mois | 58 événements pour 52 tâches : 5 ont dû être remplacées deux fois, une trois fois |

**Commande** : `python3 analysis_longitudinal.py`
**Fait foi** : `runs/longitudinal_20260815.json`

---

## 7. Export WebVoyager-Verified v0.1

| # | Affirmation | Chiffre canonique | Réserve obligatoire |
|---|---|---|---|
| 7.1 | Taille de l'export | **643 lignes**, une par tâche | ce n'est pas un audit manuel, ni une réparation, ni un verdict de vérité |
| 7.2 | Sous-ensemble consensuel | **563** (`noyau` ∪ `surveiller` ∪ `corriger`) | **ce n'est pas le nombre de tâches lançables** — le statut vient du vote des praticiens, pas de l'état de l'énoncé |
| 7.3 | Dont énoncés déjà périmés | **84 (14,9 %)** — `corriger` 63, `noyau` 14, `surveiller` 7 | 14 sont dans le `noyau`, c'est-à-dire parmi les tâches que **personne** n'a jamais signalées |
| 7.4 | **Chiffre de référence : exécutable sans retouche** | **479** | ne suppose rien du travail d'autrui. **C'est ce chiffre que le mémoire cite.** |
| 7.5 | Lançables après patch canonique valide | **536** | suppose que le patch d'un tiers est bon — or 20 des 116 patches recopiés sont eux-mêmes périmés |
| 7.6 | Patches canoniques périmés | **20** sur le corpus entier, **14** dans le sous-ensemble consensuel, **13** parmi les 84 énoncés périmés | trois dénombrements voisins qu'il ne faut pas confondre ; l'écart 13/14 est `Google Flights--9` (énoncé sain, patch périmé) |
| 7.7 | Traçabilité | **les 643 lignes portent un champ `enonce_perime`** daté et recalculable | aucune ligne n'a été retirée : la péremption est **marquée**, pas masquée |

**Décision documentée** : marquer plutôt que retirer. Trois raisons — le fichier est une
photographie à 643 lignes et retirer des lignes casserait l'invariant qui le rend comparable
dans le temps ; la péremption est **datée** et se recalcule, là où une suppression est
irréversible ; et c'est un résultat du mémoire, pas un déchet.

Formulation à employer : *« 563 tâches font consensus chez les praticiens ; 84 d'entre elles
(14,9 %) portent un énoncé déjà révolu au 15/08/2026 ; **479 sont exécutables sans
retouche**. Le mot* Verified *porte sur la réconciliation des verdicts et la datation des
mesures, jamais sur l'exécutabilité. »*

**Commande** : `python3 run_all.py --phase export`
**Fait foi** : `exports/webvoyager_verified_v0.1.stats.json`, champ `enonces_perimes`

---

## 8. Taux de signalement par catégorie — **ce ne sont pas des prévalences**

| Catégorie | Tâches portant au moins un signal | Réserve obligatoire |
|---|---:|---|
| T5 ambiguïté | 240 (**37,3 %**) | **les 240 constats ont été produits avec la rubrique fuitée** (campagne du 15/08, antérieure à la correction B1) ; la campagne n'a pas été relancée avec la rubrique propre, faute de budget. Le juge propre étant nettement plus précis et de rappel égal (§10), ce compte de 240 est **une borne haute** : avec la rubrique propre il baisserait. Citer le taux, jamais la précision, et renvoyer à `experiments/ABLATION_L3.md` pour la performance du juge. |
| T2 dérive de contenu | 187 (**29,1 %**) | 130 des constats viennent de `l1_reference`, que sa propre docstring qualifie de *proxy, pas un détecteur* ; précision mesurée **0,42** |
| T3 accès refusé | 183 (28,5 %) | pondéré par κ = 0,40 ; verdict d'URL de départ propagé au site |
| T7 fragilité d'évaluation | 163 (**25,3 %**) | **aucune vérité terrain n'existe pour T7.** 146 des 163 viennent d'un unique regex de vingt mots-clés émis en sévérité basse (confiance 0,50). Faux positifs évidents connus : `ArXiv--19`, `Google Search--19`. |
| T1 dérive temporelle | 124 (19,3 %) | la seule catégorie adossée à une précision mesurée hors échantillon |
| T4 / T8 | 7 (1,1 %) chacune | proviennent **uniquement** de l'a priori des praticiens, aucun détecteur ne les produit |
| T6 solutions multiples | 0 | aucun détecteur, aucune vérité terrain |

**Formulation à employer** : *« taux de signalement par catégorie »*, jamais *« prévalence »*.
Un jury lira « 37,3 % des tâches de WebVoyager sont ambiguës » ; ce n'est pas ce que le
chiffre dit. Ajouter systématiquement : *« seuls T1 et T5 sont adossés à une mesure de
précision ; T7 n'a aucune vérité terrain et son chiffre est le plus attaquable du dossier. »*

**Indécidées** : **273 tâches** que personne n'a jamais signalées reçoivent une note
inférieure à A (dont 29 en D). Ce sont soit des faux positifs, soit des défauts que
personne n'a regardés — **rien dans le dépôt ne permet de trancher**, il faudrait ouvrir le
site. À dire tel quel.

**Fait foi** : `runs/health_20260815.json` champ `by_category` ;
`exports/webvoyager_verified_v0.1.stats.json` champ `desaccord_outil_praticiens`

---

## 9. Figures

Les sept figures sont **déjà cohérentes avec la carte canonique** : elles lisent
`runs/health_20260815.json` et aucune autre carte. Régénération vérifiée le 16/08 —
les sept PNG sont **identiques au bit près** avant et après (seule la date de création
interne des PDF change).

```
python3 figures/make_figures.py        # 7 PNG 300 ppp + 7 PDF + figures/legendes.md
```

**Réserve, figure 5** : elle est produite depuis `runs/ablation_ambiguity_20260815.json`,
qui est l'ablation **contaminée** (fuite de rubrique, maximum publié pour une moyenne).
L'ablation propre est `runs/ablation_l3_clean_20260816.json`. **La figure 5 doit être
régénérée sur la source propre avant dépôt** — c'est le seul artefact de ce registre qui
reste à mettre à jour, et il relève de la correction B1/C1.

---

## 10. Chiffres retirés ou requalifiés — à ne plus écrire

| Ancien chiffre | Statut | Ce qu'on écrit à la place |
|---|---|---|
| « 65 tâches en note D au seul examen statique » | **tombé à 0** | « 73 tâches en note C ; aucune en D, parce qu'aucun détecteur statique n'atteint la certitude » |
| « κ = 1 → 144 tâches en D » | **faux dans la config canonique** | « κ = 1 → 177 tâches en D » |
| « 262 tâches multi-catégories (40,8 %), 83 changements de note » | **faux dans la config canonique** | « 510 (79,3 %), 122 changements » |
| « Sous-ensemble exécutable : 563 tâches » | **incomplet** | « 563 consensuelles, dont 84 périmées : **479 exécutables sans retouche** » |
| « Précision 0,986 contre six annotateurs indépendants » | **in-sample** | cf. §4.2 : le résultat hors échantillon est L1/MEDIUM, P 0,327, lift 3,55 |
| « Alumnium 03/2026 : 73/643 (11,4 %) » | **mauvais fichier** | « 55/619 (8,9 %) » — `alumnium_tasks.jsonl` est identique à l'original |
| « browser-use : 12 flags à sa naissance (1,9 %) » | **mauvais dénominateur** | « 3 flags sur 588 (0,5 %) » |
| « Contre `supprimee_1`, aucune configuration au seuil HIGH n'est significative » | **inexact** (c'est la phrase du vérificateur, pas la nôtre) | cf. §3.6 : L1+L2+L3/HIGH atteint p = 0,022 ; ce qui tient, c'est que **aucune p-valeur ne survit à la correction de multiplicité** et que le meilleur lift est 1,35 |
| « Prévalence par catégorie : T5 37,3 %, T2 29,1 %, T7 25,3 % » | **taux de signalement, pas prévalence** | conserver les chiffres, changer le titre, et noter que **T7 n'a aucune vérité terrain** et vient à 90 % d'un regex de 20 mots émis en sévérité basse |
| « Le juge LLM détecte l'ambiguïté à F1 0,83 » | **relève de la correction B1/C1** | voir `experiments/ABLATION_L3.md` et `runs/ablation_l3_clean_20260816.json` — ne rien écrire sur le juge depuis `ablation_ambiguity_20260815.json` |

---

## 11. Ce que ce registre ne couvre pas

Par honnêteté, les chiffres dont un autre chantier a la charge et qui n'entrent ici que par
renvoi : le F1 du juge L3 et son ablation propre (`experiments/ABLATION_L3.md`),
l'instruction de l'indépendance des annotateurs
(`experiments/INDEPENDANCE_ANNOTATEURS.md`), la validation hors échantillon
(`experiments/VALIDATION.md`). Leurs valeurs sont citées ci-dessus telles que leurs
fichiers de run les portent au 16/08/2026 ; si l'un de ces chantiers publie une valeur
différente, **c'est la sienne qui fait foi** et ce registre doit être corrigé, non l'inverse.

Ne sont couverts par **aucune** mesure du dépôt, et doivent donc rester hors du mémoire ou
y figurer comme limites explicites : la précision réelle des détecteurs T4, T6 et T8
(aucune vérité terrain), la part de faux positifs parmi les 273 tâches que personne n'a
signalées et que l'outil note sous A, et la reproductibilité des quatre observations
« navigateur cloud » dont dépend entièrement κ.

---

## 9 bis. AJOUTS DU 16/08/2026 (demandés par la rédaction du chapitre 3)

| # | Affirmation | Valeur canonique | Réserve obligatoire | Fait foi |
|---|---|---|---|---|
| 9b.1 | Ordonnancement par configuration (aire sous la courbe, vérité « signalée par au moins un ») | L1 **0,818** · L1+L2 **0,831** · L1+L2+L3 **0,775** | mesuré sur le corpus complet, donc in-sample pour L1 ; ce qui est robuste est le SENS (ajouter la couche modèles dégrade l'ordonnancement), pas la troisième décimale | `runs/validation_ablation_20260815.json` |
| 9b.2 | Décadence du corpus réparé par Magnitude | **0,34 % (2/590) au 06/07/2025 → 10,51 % (62/590) au 15/08/2026**, soit 60 nouveaux décès sur 588 tâches vivantes, **tous au premier semestre 2026** | **fenêtre d'observation = 13,31 mois, PAS neuf mois.** Le palier est atteint le 01/04/2026, neuf mois après la réparation, mais la mesure court sur treize mois. Taux annuel sous risque constant **9,25 % [7,25 ; 11,72]**. **NE JAMAIS ÉCRIRE « demi-vie de huit mois »** : la demi-vie sous ce modèle vaut 85,7 mois. La bonne formulation est mécanique et non statistique : la réparation tient jusqu'à l'échéance des dates qu'elle a posées. | `runs/longitudinal_20260815.json` §courbe_B_prime_corpus_repare |
| 9b.3 | Mécanisme de la rechute | **61 bombes à retardement** au jour de la réparation (dates encore à venir), horizon médian **237 jours** ; 486 tâches sans date, 25 déjà périmées, 14 sans millésime | le décompte porte sur les 590 tâches du corpus réparé | même fichier, §bombes_a_retardement |
| 9b.4 | Concentration par site des rechutes | Google Flights **31/39 (79,5 %)** · Booking **29/40 (72,5 %)** · tous les autres sites **0** | la décadence temporelle est un phénomène de deux sous-ensembles, pas du benchmark entier : à dire explicitement | même fichier, §deces_par_site |

---

## 12. AJOUTS DU 16/08/2026 — campagne « matrice des canaux »

Plan croisé complet : **15 sites × 4 canaux × 2 passes = 120 observations appariées**, produites
par `experiments/campagne_matrice.sh`, chacune accompagnée de son HAR et de sa capture.
**Fait foi** : `runs/l2_matrice_canaux_20260816.json`, `runs/matrice/`, `runs/har/`, `runs/captures/`.
Rapport : `experiments/RAPPORT_CANAUX.md`. **Recalculé indépendamment le 16/08 : les 12 κ de Cohen,
les 8 comptages de bascule, les 2 p de Fisher et la répétabilité se reproduisent tous à l'identique.**

| # | Affirmation | Chiffre canonique | Réserve obligatoire |
|---|---|---|---|
| 12.1 | Sites où le canal ne change rien | **10 / 15** | à citer avant les divergences : sur les deux tiers du corpus le canal n'a aucune importance |
| 12.2 | Sites divergents | **5 / 15** : Amazon et Booking (moteur), Allrecipes (origine), ESPN (les deux à la fois), Wolfram Alpha | **Wolfram Alpha est un faux positif du classifieur**, pas un site divergent : la chaîne `"captchaApi"` d'un objet de configuration tombe dans la fenêtre d'extrait. Capture à l'appui, la page d'accueil est normale. Ne jamais le compter comme divergence réelle. |
| 12.3 | Poids relatif des deux facteurs | **non mesurable** — moteur 4/15 contre origine 2/15, Fisher exact p = 0,651 (passe 1) et 0,390 (passe 2) | **NE JAMAIS ÉCRIRE « le moteur pèse deux fois plus que l'origine ».** Ce qui est solide est la **dissociation** : les sites que fait basculer le moteur ne sont pas ceux que fait basculer l'origine. |
| 12.4 | κ du score publié, réestimé | juge navigateur datacenter **0,50** · juge HTTP résidentiel **0,667** puis **0,833** · juge navigateur résidentiel **0,167** | **κ est une propriété d'un COUPLE, pas d'un canal.** Tous les intervalles à 95 % se recouvrent, y compris avec 0,40. **Ne pas remplacer 0,40** ; écrire κ(accusé, juge). Le 0,50 nous dessert (plus de tâches mortes) : le dire dans ce sens. |
| 12.5 | Renversement du contenu de κ | la seule confirmation qui portait 0,40 (**Booking**) est **infirmée** ; les deux nouvelles confirmations sont **Allrecipes et ESPN**, les deux réfutations d'origine | le nombre tient, les sites qui le produisent sont les inverses. C'est le résultat le plus intéressant de la campagne. |
| 12.6 | Répétabilité à une heure | **2 signatures changées sur 60 paires**, les deux sur Allrecipes | 14 sites sur 15 identiques dans les 4 cellules. **La campagne a pu provoquer le seul changement qu'elle observe** (4 sollicitations en une heure depuis la même adresse). |
| 12.7 | Le mandataire n'est pas le site | sans mandataire interposé, **GitHub passe de `channel_blocked` à `ok`** | valide rétrospectivement l'exclusion des 41 tâches GitHub du calcul de décadence |
| 12.8 | Longueur de l'extrait classifié | **3 000 caractères** (défaut du paquet ; 4 000 dans la campagne) | **paramètre de mesure, pas détail d'implémentation** : il fait à lui seul diverger deux canaux qui voient la même page. Désormais inscrit dans la configuration canonique de l'annexe A. |

**Ce que la campagne NE lève PAS, et qu'il faut continuer à écrire comme limite** : les trois
observations Browserbase n'ont pas pu être re-mesurées, faute de compte, et restent
irreproductibles. Deux des trois observations comparables divergent d'ailleurs de la cellule
navigateur-datacenter de la campagne, ce qui signifie que **« navigateur cloud » ne désigne pas un
canal tant que le fournisseur n'est pas nommé**. L'origine résidentielle est une seule adresse
mobile, d'un seul opérateur, dans un seul pays, et le contraste d'origine confond la réputation de
l'adresse, le point de présence atteint et l'édition localisée servie.

---

## 13. AJOUTS DU 18/08/2026 — campagne « vérification par archive »

Douze patches Magnitude à motif de disparition confrontés à la Wayback Machine (96 requêtes,
plafond 150, une par seconde). **Fait foi** : `runs/archive_t2_20260818.json` ; script
rejouable `experiments/verif_archive.py` ; rapport `experiments/RAPPORT_ARCHIVE.md`.
**Vérifié le 18/08 : les verdicts du JSON, le compte de requêtes et la chronologie
GitHub--29 concordent avec le rapport.**

| # | Affirmation | Chiffre canonique | Réserve obligatoire |
|---|---|---|---|
| 13.1 | Bilan des douze cas | **7 confirmés · 0 infirmé · 5 non vérifiables · 0 insuffisant** | les deux moitiés se citent ENSEMBLE : 7/12 passent du témoignage à l'observation directe, 5/12 (42 %) sont structurellement invérifiables. Jamais l'un sans l'autre. |
| 13.2 | Le zéro infirmation | **0 sur 7 vérifiables** | échantillon biaisé vers les motifs les plus confirmables (objet nommé, adresse stable). **Ne pas écrire « l'archive valide les praticiens »** : elle valide les sept motifs les plus vérifiables d'un seul patch-set. |
| 13.3 | Tâche née invalide | **GitHub--29 : la comparaison demandée était impossible dès le 02/03/2024**, jour du gel ; la fiche iPhone 14 Pro avait disparu **six mois avant le gel** (09/2023) | un dispositif datant la péremption au patch-set se tromperait de près de deux ans sur ce cas. La date de gel d'un corpus ne garantit pas la validité de son contenu à cette date. |
| 13.4 | Booking absent de l'archive | **requête CDX 1996-2026 : zéro instantané** | la part invérifiable de 13.1 est un PLANCHER : un site entier du benchmark échappe par construction à la méthode. |
| 13.5 | Ce qu'une confirmation prouve | l'existence puis la disparition d'une PAGE | **jamais l'inexécutabilité d'une tâche** : condition nécessaire, pas suffisante. Apple--2 le montre : fiche disparue, mais une route de comparaison subsistait, indécidable par archive (prix injectés en JavaScript, non archivés). |

**Formulation à employer dans le mémoire** : *« sept motifs sur douze passent du témoignage à
l'observation directe et datée ; les cinq autres sont structurellement invérifiables par
archive, et Booking échappe entièrement à la méthode. »*
