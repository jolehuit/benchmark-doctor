# Validation hors échantillon de `benchmark-doctor`

**Objet** : correction du problème bloquant **B2** de `VERIFICATION.md` — « la précision de
0,986 de L1 est intégralement in-sample » — et des problèmes **C3** (aucune ligne de base
« hasard ») et **C4** (dénominateur browser-use).
**Date** : 16/08/2026 · **Script** : `experiments/validation_hors_echantillon.py` ·
**Sortie** : `runs/validation_hors_echantillon_20260816.json`
**Coût API** : **0,00000 $** — aucun appel réseau. Le script relit les constats déjà
journalisés (`runs/health_20260815_findings.json`) et la base réconciliée
(`data/ground_truth.json`).

```
$ python3 experiments/validation_hors_echantillon.py
```

Exécution déterministe (graine 20260816) : deux exécutions successives produisent un JSON
identique octet pour octet.

---

## 1. Le problème, en une ligne

La grille publiée annonçait **précision 0,986 pour L1 au seuil HIGH**, présentée comme une
validation « contre six annotateurs ». Décomposée :

| | L1/HIGH | L1/MEDIUM | L1+L2+L3/HIGH | L1+L2+L3/MEDIUM |
|---|---:|---:|---:|---:|
| tâches signalées | 73 | 134 | 274 | 424 |
| vrais positifs | 72 | 101 | 123 | 151 |
| **dont issus du jeu d'ajustement** | **71** | 85 | 97 | 111 |
| part in-sample des vrais positifs | **98,6 %** | 84,2 % | 78,9 % | 73,5 % |
| apport des 5 autres annotateurs | **1 tâche** | 16 | 26 | 40 |

Le jeu d'ajustement est le patch-set Magnitude (121 tâches), celui sur lequel les
détecteurs L1 ont été réglés. Mesurer un détecteur sur son jeu de réglage ne mesure pas sa
capacité à généraliser : cela mesure sa capacité à mémoriser. Le 0,986 est **entièrement**
in-sample, pas « partiellement ».

---

## 2. Le protocole

**Scission stricte.** Jeu d'ajustement *A* = les 121 tâches patchées par Magnitude. Jeu de
validation *V* = les **522 tâches restantes**. `A ∩ V = ∅`, vérifié à l'exécution par
assertion. Aucune décision de Magnitude ne porte sur *V*.

**Vérité de validation.** Quatre lectures, toutes construites **sans Magnitude** :

| clé | définition | n | prévalence |
|---|---|---:|---:|
| **`autres_1`** *(référence)* | signalée par ≥ 1 des 5 annotateurs autres que Magnitude | 48 | **0,0920** |
| `autres_2` | signalée par ≥ 2 des 5 | 15 | 0,0287 |
| `hors_lignee_1` | signalée par ≥ 1 des **4** annotateurs sans filiation avec Magnitude (Convergence exclue, cf. B3 : 56/60 réécritures identiques au caractère près) | 45 | 0,0862 |
| `supprimee_autres_1` | **retirée** du corpus par ≥ 1 des 5 autres | 20 | 0,0383 |

**Trois colonnes obligatoires sur chaque ligne** — une ligne qui n'en dispose pas n'est pas
interprétable et ne doit plus être publiée :

1. **précision au hasard** = la prévalence de la vérité. C'est ce qu'obtiendrait un
   détecteur tirant au sort. Sans elle, « précision 0,33 » ne dit ni bien ni mal ;
2. **lift** = précision observée / précision au hasard. Un lift de 1,0 est un résultat nul,
   quel que soit le chiffre de précision affiché ;
3. **test binomial unilatéral** *H₀ : p ≤ π₀* et sa p-value.

**Correction du groupement par site** (voir §4) : deux tests supplémentaires et un
intervalle de confiance en clusters, parce que le test binomial suppose des tâches
indépendantes et qu'elles ne le sont pas.

**Contrôle de multiplicité** : douze configurations sont testées contre la même vérité.
Procédure de **Holm-Bonferroni** descendante à α = 5 %, valide sans hypothèse
d'indépendance entre tests.

---

## 3. La grille hors échantillon — 522 tâches, vérité `autres_1` (prévalence 0,0920)

C'est la grille de référence du mémoire.

| Config | Seuil | Signalées | VP | **P** | **P hasard** | **Lift** | R | **p binom.** | **p corrigée site** | IC 95 % lift (clusters) | Holm 5 % |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| **L1** | **HIGH** | **2** | **1** | 0,500 | 0,092 | 5,44 | **0,021** | 0,175 | 0,174 | [0,00 ; 14,27] | non |
| **L1** | **MEDIUM** | **49** | **16** | **0,327** | 0,092 | **3,55** | 0,333 | **4,49·10⁻⁶** | **3,57·10⁻³** | **[1,78 ; 7,46]** | **oui** |
| L2 | HIGH | 126 | 18 | 0,143 | 0,092 | 1,55 | 0,375 | 0,0404 | **0,0908** ᔆ | [0,78 ; 4,01] | non |
| L2 | MEDIUM | 126 | 18 | 0,143 | 0,092 | 1,55 | 0,375 | 0,0404 | **0,0908** ᔆ | [0,78 ; 4,01] | non |
| L3 | HIGH | 67 | 12 | 0,179 | 0,092 | 1,95 | 0,250 | 0,0183 | 0,0106 | [1,31 ; 2,68] | non |
| L3 | MEDIUM | 238 | 26 | 0,109 | 0,092 | 1,19 | 0,542 | 0,206 | 0,0828 | [0,92 ; 1,60] | non |
| L1+L2 | HIGH | 127 | 18 | 0,142 | 0,092 | 1,54 | 0,375 | 0,0431 | 1,000 | [0,71 ; 3,81] | non |
| L1+L2 | MEDIUM | 164 | 28 | 0,171 | 0,092 | 1,86 | 0,583 | 1,05·10⁻³ | 0,0503 | [1,20 ; 3,83] | non |
| L1+L3 | HIGH | 67 | 12 | 0,179 | 0,092 | 1,95 | 0,250 | 0,0183 | 0,0106 | [1,31 ; 2,68] | non |
| L1+L3 | MEDIUM | 267 | 33 | 0,124 | 0,092 | 1,34 | 0,688 | 0,0506 | 0,0586 | [1,05 ; 1,78] | non |
| L1+L2+L3 | HIGH | 177 | 26 | 0,147 | 0,092 | 1,60 | 0,542 | 0,0117 | 0,0183 | [1,11 ; 2,51] | non |
| L1+L2+L3 | MEDIUM | 313 | 40 | 0,128 | 0,092 | 1,39 | 0,833 | 0,0217 | 0,0312 | [1,14 ; 1,77] | non |

ᔆ = ensemble signalé constitué de **sites entiers** : la p-value corrigée est le test de
permutation exact au niveau site (1 365 permutations énumérées). Pour toutes les autres
lignes, c'est le test exact conditionnel stratifié intra-site.

**Holm à α = 5 % sur les douze lignes : une seule survivante, `L1/MEDIUM`** (p = 3,57·10⁻³
contre un seuil de 0,05/12 = 4,17·10⁻³). La deuxième, `L3/HIGH` (p = 0,0106), échoue contre
0,05/11 = 4,55·10⁻³.

### Les mêmes configurations contre les trois autres vérités

| Config · seuil | `autres_2` (π = 0,029) | `hors_lignee_1` (π = 0,086) | `supprimee_autres_1` (π = 0,038) |
|---|---|---|---|
| L1 · HIGH | 0/2 · lift 0 · p = 1 | 1/2 · lift 5,80 · p = 0,174 | 0/2 · lift 0 · p = 1 |
| **L1 · MEDIUM** | 8/49 · **lift 5,68** · p = 0,0175 | 15/49 · **lift 3,55** · p = **4,12·10⁻³** | 2/49 · lift 1,07 · p = 0,229 |
| L2 · HIGH | 11/126 · lift 3,04 · p = 0,022 ᔆ | 18/126 · lift 1,66 · p = 0,067 ᔆ | 7/126 · lift 1,45 · p = 0,197 ᔆ |
| L3 · HIGH | 1/67 · lift 0,52 · p = 0,879 | 12/67 · lift 2,08 · p = 6,4·10⁻³ | 6/67 · lift 2,34 · p = 0,157 |
| L1+L2+L3 · MEDIUM | 15/313 · lift 1,67 · p = 0,187 | 39/313 · lift 1,45 · p = 9,0·10⁻³ | 15/313 · lift 1,25 · p = 0,381 |

Survivantes de Holm par vérité : `hors_lignee_1` → **`L1/MEDIUM`** ; `autres_2` → aucune ;
`supprimee_autres_1` → **aucune**.

Deux lectures s'imposent.

- **`L1/MEDIUM` est la seule ligne qui traverse les quatre vérités sans s'effondrer**, y
  compris `hors_lignee_1` qui retire Convergence, l'annotateur de la même lignée que le jeu
  d'ajustement. C'est le résultat du mémoire.
- **Contre `supprimee_autres_1` — « un praticien a retiré la tâche » — aucune configuration
  n'est significative, à aucun seuil.** C'est un résultat nul, il doit être écrit comme tel.
  Il est défendable en soutenance (« nos détecteurs voient ce qui *se périme*, pas ce qu'un
  praticien *décide de retirer* ») ; le passer sous silence ne l'est pas.

---

## 4. La correction du groupement par site

### Pourquoi le test binomial était trop favorable

La couche L2 mesure l'accès **par site** et propage un constat unique à toutes les tâches
du site. Dans le jeu de validation, `L2/HIGH` signale 126 tâches — mais ce sont **quatre
décisions**, pas 126 :

| Site | tâches (dans *V*) | signalées par L2/HIGH | positifs |
|---|---:|---:|---:|
| Allrecipes | 40 | **40** | 2 |
| Amazon | 38 | **38** | 4 |
| Booking | 11 | **11** | 5 |
| ESPN | 37 | **37** | 7 |
| les 11 autres sites | 396 | 0 | 30 |

(Sur le corpus complet de 643 tâches, c'est Allrecipes 45/45, Amazon 41/41, Booking 44/44,
ESPN 44/44, plus une unique tâche Huggingface signalée par `l2_content`.)

Un test binomial sur *n* = 126 traite ces quatre décisions comme 126 observations
indépendantes et gonfle mécaniquement la significativité : il divise l'écart-type par
√126 ≈ 11 là où il faudrait le diviser par √4 = 2.

### Les deux corrections appliquées

**(a) Test exact conditionnel stratifié par site** — appliqué à toutes les lignes. Sous
*H₀*, les *f_s* constats du site *s* sont placés au hasard parmi ses *n_s* tâches, dont
*c_s* sont positives : le nombre de vrais positifs du site suit
`Hypergeom(n_s, c_s, f_s)`, et le total suit la convolution de ces lois, calculée
**exactement** (pas de Monte-Carlo). Ce test ne crédite jamais un détecteur pour avoir
deviné le bon *site* — seulement pour avoir désigné les bonnes *tâches* dans un site. Un
détecteur qui signale des sites entiers y obtient p = 1,000 par construction : la
distribution est dégénérée. C'est le comportement voulu, et c'est exactement ce qui arrive
à `L2` (p = 1,000 exactement).

**(b) Test de permutation exact au niveau site** — quand l'ensemble signalé est une réunion
de sites entiers, l'unité d'observation est le site. On énumère les C(15, 4) = **1 365**
façons de choisir 4 sites parmi les 15 et l'on compte celles qui atteignent au moins la
précision observée. Aucune approximation.

**(c) Intervalle de confiance en clusters** — bootstrap non paramétrique rééchantillonnant
les **15 sites** avec remise (20 000 réplicats, graine 20260816), percentiles 2,5 % et
97,5 % sur la précision et sur le lift. Avec 15 clusters seulement, l'intervalle est large :
c'est une information honnête, pas une précision retrouvée.

### L'effet, chiffré

| Ligne | p binomiale (i.i.d.) | p corrigée site | conclusion |
|---|---:|---:|---|
| **L2 · HIGH** | **0,0404** *(significatif)* | **0,0908** *(non significatif)* | la significativité de L2 était un artefact du dénominateur |
| L2 · MEDIUM | 0,0404 | 0,0908 | idem (L2 n'émet que `info` ou `high` : les deux seuils sont le même test) |
| L1+L2 · HIGH | 0,0431 | 1,000 | ⚠ voir ci-dessous |
| L1+L2 · MEDIUM | 1,05·10⁻³ | 0,0503 | bascule au-dessus de 5 % |
| L1+L2+L3 · MEDIUM | 0,0217 | 0,0312 | tient, mais lift 1,39 |
| **L1 · MEDIUM** | **4,49·10⁻⁶** | **3,57·10⁻³** | **tient** — trois ordres de grandeur perdus, le résultat reste |

Le p = 1,000 de `L1+L2/HIGH` n'est pas un bug : hors échantillon, L1/HIGH n'ajoute qu'une
seule tâche aux 126 sites de L2 (`GitHub--40`), et c'est un faux positif. Le nombre de vrais
positifs observé est donc le **minimum** atteignable sous *H₀* stratifiée, ce qui donne
mécaniquement p = 1 pour un test unilatéral. La lecture est correcte : à ce seuil, hors
échantillon, L1 n'apporte rien à L2.

### Pourquoi `L1/MEDIUM` résiste

Ses 49 constats sont répartis sur **9 sites sur 15** (Apple 21, Booking 7, Google Flights 7,
GitHub 5, Amazon 4, Google Search 2, ArXiv 1, Coursera 1, Huggingface 1) : ce n'est pas un
effet de site. Retrait d'un site à la fois (*leave-one-site-out*), quinze mesures :

| site retiré | signalées | VP | P | lift | p corrigée site |
|---|---:|---:|---:|---:|---:|
| Apple | 28 | 13 | 0,464 | 5,43 | 5,3·10⁻⁵ |
| ArXiv | 48 | 16 | 0,333 | 3,64 | 2,5·10⁻³ |
| Google Search | 47 | 16 | 0,340 | 3,50 | 2,9·10⁻³ |
| Allrecipes / BBC / Cambridge / Coursera / ESPN / Google Map / Wolfram | 48-49 | 16 | 0,327-0,333 | 3,3-3,9 | 3,6·10⁻³ |
| Google Flights | 42 | 13 | 0,309 | 3,54 | 5,2·10⁻³ |
| Amazon | 45 | 15 | 0,333 | 3,67 | 5,3·10⁻³ |
| Huggingface | 48 | 15 | 0,312 | 3,38 | 0,014 |
| **Booking** | 42 | 11 | 0,262 | 3,11 | **0,031** |
| **GitHub** | 44 | 13 | 0,295 | 3,17 | **0,106** |

Le cas le plus défavorable est le retrait de **GitHub** : p = 0,106, non significatif. Il
faut le dire — le résultat n'est pas insensible au corpus. Mais le lift reste à 3,17 dans ce
cas, et quatorze retraits sur quinze laissent p ≤ 0,031.

---

## 5. L1 contre chaque annotateur, pris séparément

La mesure la plus décontaminée du dossier. **Fara** (31/08/2025) et **Alumnium**
(17/03/2026) n'ont aucune filiation connue avec Magnitude ni entre eux, et leurs verdicts
portent ici sur des tâches que Magnitude n'a jamais touchées.

| Annotateur | n positifs (sur 522) | prévalence | L1/MEDIUM : VP/49 | P | lift | p corrigée site |
|---|---:|---:|---:|---:|---:|---:|
| **Microsoft Fara** | 26 | 0,050 | **11** | 0,225 | **4,51** | **6,45·10⁻⁴** |
| **Alumnium** | 13 | 0,025 | **6** | 0,122 | **4,92** | 0,082 |
| browser-use | 9 | 0,017 | 3 | 0,061 | 3,55 | 0,039 |
| Skyvern 05/2026 | 17 | 0,033 | 4 | 0,082 | 2,51 | 0,754 |
| Convergence *(même lignée que Magnitude)* | 5 | 0,010 | 1 | 0,020 | 2,13 | 0,878 |

`L1/HIGH` : 0 vrai positif contre chacun des quatre annotateurs hors browser-use, et 1/2
contre browser-use.

**Lecture** : le lift de `L1/MEDIUM` se retrouve à 3,5-4,9 chez quatre annotateurs sur cinq,
avec un seul significatif à 5 % après correction et contrôle de multiplicité (Fara). Ce
n'est pas un accord unanime : c'est un signal cohérent et faible, mesuré indépendamment
quatre fois. C'est ce qu'on peut affirmer, et rien de plus.

---

## 6. Le dénominateur browser-use (problème C4), corrigé et répercuté

`browseruse_tasks.jsonl` contient **encore les 55 identifiants** que browser-use a lui-même
déclarés impossibles (`WebVoyagerImpossibleTasks.json`). Le corpus réel du fork est de
**588 tâches**, pas 643.

| lecture | n | à sa naissance (15/12/2024) | au 15/08/2026 | risque annuel |
|---|---:|---:|---:|---:|
| publiée (fichier brut) | 643 | 12 (1,9 %) | 72 (11,2 %) | 5,8 %/an |
| **corrigée (corpus réel)** | **588** | **3 (0,5 %)** | **62 (10,5 %)** | **6,2 %/an** |

**Neuf des douze constats « à sa naissance » portaient sur des tâches que browser-use avait
déjà retirées** : `Booking--11`, `Booking--13`, `Booking--14`, `Google Flights--0`,
`Google Flights--20`, `Google Map--13`, `Google Map--18`, `Google Map--26`,
`Google Search--15`. Le taux publié à la naissance valait près de quatre fois le vrai.

Répercussions effectuées :

- `analysis_longitudinal.py` : `FORKS` porte désormais, par fork, le fichier de ses
  exclusions déclarées ; `forks_health()` les retire avant de mesurer, et journalise
  `n_lignes_du_fichier` et `n_exclusions_declarees_retirees` ;
- `runs/longitudinal_20260815.json` régénéré. **Le diff est intégralement contenu dans la
  ligne browser-use** : aucune autre mesure du rapport longitudinal ne bouge, et
  `runs/longitudinal_curves_20260815.csv` est identique octet pour octet ;
- `README.md` : ligne du tableau des sept forks corrigée, avec la note explicative.

La correction **renforce** la thèse au lieu de l'affaiblir : browser-use naît quasi
parfaitement sain (3/588 = 0,5 %) et revient à 10,5 % en vingt mois. « Forker ne guérit pas,
cela remet une horloge à zéro » est plus vrai après correction qu'avant.

---

## 7. Verdict : que peut-on encore affirmer de L1 ?

**`L1/HIGH` : rien qui soit validable hors échantillon.** Sur les 522 tâches que le
patch-set d'ajustement n'a jamais touchées, il signale **2 tâches** (rappel 0,021), dont une
correcte, p = 0,17. Le test n'est pas sans puissance : un score parfait de 2/2 aurait donné
p = 0,0085, donc significatif. C'est le détecteur qui est muet, pas le test qui est aveugle.
71 de ses 73 constats sur le corpus complet tombent dans le jeu d'ajustement — la « précision
de 97 % » n'existe qu'à l'intérieur du corpus qui a servi à la produire.

**`L1/MEDIUM` : oui, et c'est le résultat de référence du mémoire.** Précision **0,327**
contre **0,092** attendu au hasard, **lift 3,55**, rappel 0,333, p binomiale 4,5·10⁻⁶ et
p = **3,6·10⁻³** après stratification par site. C'est :

- la **seule** des douze configurations à survivre au contrôle de multiplicité de Holm ;
- stable sur quatorze des quinze retraits de site (pire cas : sans GitHub, p = 0,106) ;
- stable quand on retire Convergence de la vérité (p = 4,1·10⁻³) ;
- retrouvée indépendamment contre Fara (lift 4,51, p = 6,4·10⁻⁴) et Alumnium (lift 4,92).

**`L2` : résultat nul hors échantillon.** Sa significativité apparente (p = 0,040) venait
entièrement du dénominateur : 126 tâches signalées = 4 sites. Au niveau site, p = 0,091.

**La campagne complète au seuil MEDIUM** signale 313 des 522 tâches (60 %) pour un rappel de
0,833 et un **lift de 1,39** (p = 0,031, non retenu après Holm). Un tirage au hasard de 313
tâches obtiendrait déjà un rappel de 0,60 : c'est un outil de tri, pas un verdict.

---

## 8. Ce que ce protocole ne corrige pas — à dire en soutenance

1. **La scission est disjointe sur les positifs, pas sur les négatifs.** Aucune tâche de *V*
   n'a été patchée par Magnitude, mais le réglage des détecteurs a consisté pour partie à
   supprimer des faux positifs, donc à regarder des tâches non patchées. Deux éléments
   bornent cette contamination résiduelle sans l'annuler : aucun identifiant de tâche n'est
   codé en dur dans une décision de détecteur (vérifié), et les corrections sont des règles
   linguistiques générales. Le chiffre hors échantillon reste une **borne haute** — mais
   d'un ordre de grandeur plus honnête que le chiffre in-sample.
2. **La vérité de validation n'est pas une vérité terrain**, c'est le jugement d'autres
   praticiens, faillible et non motivé pour la plupart des sources. Un faux positif peut
   être une tâche réellement défectueuse que personne n'a encore signalée. Le silence d'une
   source compte comme « conserver » même si elle n'a jamais examiné la tâche : la précision
   mesurée est donc une borne basse, et le rappel une borne haute.
3. **15 clusters, c'est peu.** Les intervalles bootstrap sont larges et le test de
   permutation au niveau site ne dispose que de 1 365 permutations. Aucune correction ne
   crée de l'information qui n'existe pas : sur quatre décisions de site, on ne conclut pas.
4. **Les mesures portent sur les constats des détecteurs, jamais sur le score de stabilité
   publié** : celui-ci intègre un a priori tiré de la même base de vérité, et le valider
   contre elle serait circulaire.

---

## 9. La formulation exacte à reprendre dans le mémoire

> **Chapitre 4, résultats — remplace « précision 0,986 contre six annotateurs indépendants ».**
>
> « Mesurée sur l'ensemble du corpus, la couche L1 au seuil HIGH atteint une précision de
> 0,986 contre la vérité "signalée par au moins un des six patch-sets". Ce chiffre n'est pas
> une performance de détection : **71 de ses 72 vrais positifs sont des tâches du patch-set
> Magnitude, celui-là même sur lequel nous avons réglé les détecteurs**, et l'apport des cinq
> autres annotateurs se réduit à une tâche. Nous avons donc construit une validation hors
> échantillon : le jeu de réglage (les 121 tâches patchées par Magnitude) et le jeu de
> validation (les 522 autres) sont strictement disjoints, et la vérité de validation ne fait
> intervenir que les cinq annotateurs restants (48 positifs, prévalence 9,2 %).
>
> Hors échantillon, **L1 au seuil HIGH ne signale plus que deux tâches sur 522**, dont une
> correcte (p = 0,17) : c'est un régime de très haute précision que le corpus disponible ne
> permet pas de valider, faute de constats. **Le résultat que nous retenons est L1 au seuil
> MEDIUM : précision 0,327 contre 0,092 attendu au hasard, soit un lift de 3,55, pour un
> rappel de 0,333** (p = 4,5·10⁻⁶ par test binomial unilatéral ; p = 3,6·10⁻³ après
> stratification par site, les constats d'accès étant propagés site par site). C'est la seule
> des douze configurations testées qui survive au contrôle de multiplicité de Holm, elle
> résiste au retrait de quatorze des quinze sites, et elle se retrouve indépendamment contre
> deux annotateurs sans filiation avec le jeu de réglage (Fara : lift 4,51, p = 6,4·10⁻⁴ ;
> Alumnium : lift 4,92). Contre la vérité la plus stricte — "un praticien a retiré la tâche"
> — **aucune configuration n'est significativement meilleure que le hasard** : nos détecteurs
> voient ce qui se périme, pas ce qu'un praticien décide de retirer. »

> **Chapitre 3 ou 6, méthode — la phrase sur le groupement par site.**
>
> « Toute p-value calculée tâche par tâche surestime la significativité de la couche L2 :
> celle-ci mesure l'accès par site et propage un constat unique à l'ensemble des tâches de
> l'hôte. Dans le jeu de validation, ses 126 tâches signalées sont **quatre décisions de
> site** (Allrecipes 40/40, Amazon 38/38, Booking 11/11, ESPN 37/37). Nous publions donc, à
> côté du test binomial, un test exact conditionnel stratifié par site et, lorsque l'ensemble
> signalé est une réunion de sites entiers, un test de permutation exact au niveau site
> (1 365 permutations énumérées), ainsi qu'un intervalle de confiance obtenu par bootstrap
> des clusters. La significativité apparente de L2 (p = 0,040) ne survit pas à cette
> correction (p = 0,091) : c'était un artefact du dénominateur. »

> **Chapitre 4 — la ligne browser-use du tableau des forks.**
>
> « Chaque fork est mesuré sur son corpus réel, exclusions déclarées retirées : browser-use
> compte 588 tâches et non les 643 lignes de son fichier, qui embarque encore les
> 55 identifiants qu'il a publiquement retirés. Sans cette correction, neuf des douze
> constats émis "à sa naissance" portaient sur des tâches qu'il ne faisait plus tourner, et
> son taux de naissance était multiplié par près de quatre (1,9 % au lieu de 0,5 %). »

### Trois phrases à ne plus écrire

| ❌ à bannir | ✅ à écrire |
|---|---|
| « L1 atteint une précision de 0,986 » (seul) | « 0,986 in-sample ; 0,327 hors échantillon au seuil MEDIUM, contre 0,092 au hasard » |
| « six annotateurs **indépendants** » | « six patch-sets, dont deux d'une même lignée » (cf. B3) |
| « la campagne complète atteint un rappel de 0,89 » | « … en signalant 66 % du corpus, soit un lift de 1,35 » |
