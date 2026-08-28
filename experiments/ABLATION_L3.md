# Ablation L3 — détection d'ambiguïté, rubrique propre

**Mesure du 16/08/2026** · corrige les problèmes **B1**, **C1**, **C2** et **C13** de la
vérification adverse (`VERIFICATION.md`) · **remplace** `runs/ablation_ambiguity_20260815.json`
et le tableau L3 du rapport 4.
Artefact : `runs/ablation_l3_clean_20260816.json` · banc : `experiments/ablation_l3_clean.py`
· coût réel de la campagne : **0,27020 $** (champ `usage.cost`, 2 224 appels facturés,
1 251 servis par le cache).

---

## 1. Le résultat en une ligne

> **Le juge LLM ne détecte pas l'ambiguïté à F1 0,83. Il l'atteint à F1 0,715 ± 0,006, et
> l'essentiel de ce qu'il fait est de reproduire la grille d'annotation qu'on lui a
> transmise.**

Le chiffre publié le 15/08 — `F1 0,827 ± 0,058` — cumulait trois défauts qui jouaient tous
dans le même sens :

| Défaut | Effet sur le F1 publié |
|---|---:|
| **B1** — cinq énoncés du jeu évalué recopiés dans la rubrique du juge (4 positifs, 1 négatif) | **−0,095** |
| **C1** — le maximum de quatre exécutions publié comme s'il était une moyenne | **−0,017** |
| **C2** — seuil calibré par maximisation du F1 (sans effet ici, voir §6) | 0,000 |
| **Total** | **0,827 → 0,715** |

*(Le 0,827 publié est la moyenne inter-plis de l'exécution `v1` ; son F1 hors plis vaut
0,826. Les deux estimateurs diffèrent de 0,001 sur ce jeu, ce qui ne change aucune des
lignes ci-dessus. Toutes les valeurs du présent rapport sont des F1 **hors plis**.)*

Le résultat L3 **ne tombe pas, mais il change de nature** : ce n'est plus un détecteur qui
gagne 0,19 point de F1 sur une ligne de base gratuite, c'est un détecteur **de haute
précision** (0,89 contre 0,66) **à rappel identique** (0,60 pour les deux), dont l'avantage
en F1 n'est pas significatif à 5 % sur 139 items. Voir §5 : c'est la formulation à
défendre.

---

## 2. Ce qui a été corrigé, et comment

### 2.1 B1 — la rubrique du juge (`benchmark_doctor/detectors/l3_ambiguity.py`)

L'ancienne rubrique contenait des formulations du jeu évalué. La vérification en avait
relevé quatre ; le contrôle automatisé écrit pour l'occasion en trouve **cinq dans le jeu
annoté, et sept dans le corpus complet** :

| Formulation de la rubrique | Tâche | Dans le jeu annoté ? | Étiquette |
|---|---|---|---|
| « at least 500 stars » | `GitHub--5` | oui | **1** (A1) |
| « at least 500 stars » | `GitHub--17` | non (mais notée par la carte de santé) | — |
| « renowned university » | `Coursera--0` | oui | **1** (A1+A2) |
| « innovative and widely recognized » | `Huggingface--23` | oui | **1** (A2+A4) |
| « the latest iPad model » | `Apple--11` | oui | **1** (A3) |
| « the latest iPad model » | `Apple--8` | non (mais notée par la carte de santé) | — |
| « most starred » (dans la liste des **non**-ambiguës) | `GitHub--28` | oui | **0** |

Le cinquième item annoté — `GitHub--28`, un **négatif** dont le trait distinctif
(« most starred ») figurait dans la liste des contre-exemples — avait échappé à la
vérification. La fuite portait donc dans les deux sens : quatre positifs et un négatif.

La rubrique est réécrite avec des exemples **entièrement fabriqués**, sur des domaines
choisis pour n'appartenir à aucun des quinze sites de WebVoyager (halage et mouillage
fluvial, camping, dépôt d'autocars, artisanat, archives d'un club). La règle est écrite en
commentaire dans le module et **rendue exécutable** par
`experiments/check_rubric_leak.py`, qui applique quatre contrôles et qui **échoue sur
l'ancienne rubrique** (`--old`) tout en passant sur la nouvelle :

```
$ python experiments/check_rubric_leak.py --both
=== rubrique « 15/08 — fuitée » ===
1. suites de ≥4 mots reprises d'un énoncé du corpus : 5
2. marqueurs de domaine des 15 sites : 8      (ipad, hotel, dictionary, course,
                                               university, repo, repositor, stars)
3. mots d'exemple rares partagés avec le corpus : 7   (innovative, product, recognized,
                                               renowned, repo, starred, widely)
4. recouvrement lexical maximal : 55 % (GitHub--5, label 1)
ÉCHEC ×3

=== rubrique « 16/08 — courante » ===
1. 0   2. 0   3. 0   4. recouvrement maximal 27 % (BBC News--35)
rubrique propre : aucun énoncé, aucune paraphrase et aucun domaine du corpus évalué.
```

**Ce que ce contrôle ne corrige pas, et ne peut pas corriger** : le juge reçoit toujours la
*définition* de l'étiquette, celle-là même qu'a suivie l'annotateur. Voir §7.

### 2.2 C1 — moyenne et écart-type, jamais le maximum

Chaque juge est exécuté **cinq fois** (variantes de cache indépendantes, même prompt, même
température 0). Le tableau publie la moyenne et l'écart-type **inter-exécutions**, nommé
comme tel, à côté de l'écart-type **inter-plis**, nommé lui aussi. Les cinq exécutions de
l'ancienne rubrique reproduisent exactement les quatre valeurs de la vérification
(0,804 / 0,826 / 0,815 / 0,792) et en ajoutent une cinquième (0,811).

Le `± 0,058` publié était la dispersion **entre plis de l'exécution `v1`** — soit
l'incertitude d'échantillonnage du meilleur tirage, présentée comme l'incertitude du
résultat.

### 2.3 C2 — calibration sur le J de Youden

Le seuil principal est désormais celui qui maximise `J = sensibilité + spécificité − 1`,
calibré sur les plis d'entraînement. Le J vaut **exactement 0** pour la stratégie « tout
positif », qui ne peut donc plus être choisie ; le F1, lui, n'a pas de terme en vrais
négatifs et la sélectionne dès que le classifieur est faible. Le tableau au **seuil fixe
0,5** est publié en regard (§4), et l'ancien critère est conservé comme témoin (§6).

### 2.4 C13 — aucune métrique in-sample

Toutes les lignes du rapport sont hors plis. La précision apparente du backend `tfidf`
appliqué aux 139 tâches qui l'ont entraîné est recalculée **uniquement pour être
disqualifiée** :

```
tfidf, seuil 0,5 : précision in-sample 0,964 (55 signalements)
                   précision hors plis  0,660 (50 signalements)
```

Le rapport 15/08 publiait `0,654` hors plis (seuil max-F1) — la valeur est reproduite au
millième près par ce banc. C'est celle-là, et jamais 0,964, qui doit figurer au mémoire.

---

## 3. Protocole

Identique à celui du 15/08 sur tout ce qui n'est pas listé au §2 — c'est la condition pour
que le tableau avant/après soit un tableau et pas deux mesures différentes.

- **Jeu** : `data/annotations_ambiguity.json`, 139 tâches WebVoyager, 55 positives
  (39,6 %), annotateur unique (un LLM), rubrique écrite avant l'étiquetage.
- **Validation croisée** : 5 plis stratifiés, graine 42, **mêmes plis pour toutes les
  approches** (`stratified_folds` importée du banc d'origine, non réimplémentée).
- **Seuil** : calibré sur les plis d'entraînement seulement, jamais sur le pli de test.
- **Ce qui n'apprend pas des étiquettes** (encodeurs figés, juge) est calculé une fois
  hors de la boucle de validation.
- **Juges** : `google/gemini-2.5-flash` (et `-lite` en contrôle), température 0,
  `max_tokens` 120, 5 exécutions par famille.
- **Coût** : lu dans `usage.cost` de la réponse OpenRouter, jamais estimé depuis une grille
  tarifaire.

---

## 4. Le tableau

### Tableau principal — seuil J de Youden, hors plis

| Approche | P | R | **F1** | AUC | σ inter-plis | σ inter-exéc. | Coût / 139 |
|---|---:|---:|---:|---:|---:|---:|---:|
| référence — tout positif | 0,396 | 1,000 | 0,567 | 0,500 | 0,007 | — | 0 $ |
| référence — majorité par site | 0,567 | 0,691 | 0,623 | 0,746 | 0,118 | — | 0 $ |
| référence — règle lexicale à la main | 0,676 | 0,455 | 0,543 | 0,656 | 0,218 | — | 0 $ |
| **(a) TF-IDF 1-2 grammes + rég. log.** | 0,660 | 0,600 | **0,629** | 0,776 | 0,124 | — | 0 $ |
| **(b) all-MiniLM-L6-v2 (384 d) + rég. log.** | 0,543 | 0,691 | **0,608** | 0,732 | 0,120 | — | 0 $ |
| **(c) text-embedding-3-small (1536 d) + rég. log.** | 0,621 | 0,655 | **0,637** | 0,787 | 0,121 | — | 0,00007 $ |
| **(d) juge `gemini-2.5-flash` — rubrique PROPRE** | 0,891 ± 0,001 | 0,596 ± 0,008 | **0,715 ± 0,006** | 0,772 ± 0,004 | 0,175 | 0,006 | 0,13524 $ |
| (d⁻) juge `gemini-2.5-flash` — rubrique FUITÉE (15/08) | 0,831 ± 0,007 | 0,789 ± 0,021 | *0,810 ± 0,012* | 0,848 ± 0,013 | 0,078 | 0,012 | 0,14192 $ |
| (d⁰) juge `gemini-2.5-flash` — **sans** rubrique | 0,448 ± 0,012 | 0,764 ± 0,055 | 0,565 ± 0,024 | 0,627 ± 0,009 | 0,072 | 0,024 | 0,07468 $ |
| (e) juge `gemini-2.5-flash-lite` — rubrique PROPRE | 0,627 ± 0,036 | 0,153 ± 0,021 | 0,245 ± 0,029 | 0,551 ± 0,010 | 0,129 | 0,029 | 0,03961 $ |
| (e⁻) juge `gemini-2.5-flash-lite` — rubrique FUITÉE | 0,686 ± 0,016 | 0,382 ± 0,026 | 0,490 ± 0,022 | 0,645 ± 0,005 | 0,234 | 0,022 | 0,03644 $ |

*La ligne (d⁻) est publiée pour mesurer la fuite, pas comme un résultat. Elle ne doit
apparaître au mémoire qu'accompagnée de la ligne (d).*

### Tableau au seuil fixe 0,5 (aucune calibration)

| Approche | P | R | **F1** |
|---|---:|---:|---:|
| référence — tout positif | 0,396 | 1,000 | 0,567 |
| référence — majorité par site | 0,567 | 0,691 | 0,623 |
| référence — règle lexicale à la main | 0,676 | 0,455 | 0,543 |
| (a) TF-IDF | 0,681 | 0,582 | **0,627** |
| (b) MiniLM | 0,586 | 0,618 | **0,602** |
| (c) embeddings OpenRouter | 0,618 | 0,618 | **0,618** |
| **(d) juge flash — rubrique propre** | 0,891 ± 0,001 | 0,596 ± 0,008 | **0,715 ± 0,006** |
| (d⁻) juge flash — rubrique fuitée | 0,831 ± 0,007 | 0,789 ± 0,021 | 0,810 ± 0,012 |
| (d⁰) juge flash — sans rubrique | 0,500 ± 0,014 | 0,225 ± 0,010 | 0,311 ± 0,011 |
| (e) juge flash-lite — rubrique propre | 0,616 ± 0,028 | 0,145 ± 0,013 | 0,235 ± 0,017 |
| (e⁻) juge flash-lite — rubrique fuitée | 0,689 ± 0,015 | 0,371 ± 0,016 | 0,482 ± 0,017 |

**Le classement ne change pas entre les deux tableaux**, et pour le juge `flash` les deux
sont identiques au millième : son seuil de Youden vaut 0,50 dans les 25 plis des cinq
exécutions. Le résultat principal ne dépend donc **d'aucun choix de calibration** — c'est
la seule bonne nouvelle de ce rapport, et elle mérite d'être dite en soutenance.

### Les cinq exécutions, une par une (F1 hors plis)

| Juge | 1 | 2 | 3 | 4 | 5 | moyenne | σ | étendue |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| **(d) flash — rubrique propre** | 0,717 | 0,717 | 0,703 | 0,717 | 0,717 | **0,715** | 0,006 | 0,703–0,717 |
| (d⁻) flash — rubrique fuitée | 0,804 | 0,826 | 0,815 | 0,792 | 0,811 | 0,810 | 0,012 | 0,792–0,826 |
| (d⁰) flash — sans rubrique | 0,545 | 0,554 | 0,554 | 0,607 | 0,564 | 0,565 | 0,024 | 0,545–0,606 |
| (e) flash-lite — rubrique propre | 0,212 | 0,286 | 0,235 | 0,261 | 0,232 | 0,245 | 0,029 | 0,212–0,286 |
| (e⁻) flash-lite — rubrique fuitée | 0,517 | 0,512 | 0,476 | 0,471 | 0,476 | 0,490 | 0,022 | 0,471–0,517 |

Les quatre premières valeurs de la ligne (d⁻) sont **exactement** celles de la
vérification adverse : la reproduction est bit à bit (cache servi, 0 appel réseau pour
ces quatre-là).

---

## 5. Ce que le juge achète réellement

C'est la partie du rapport qui a le plus changé de sens, et la seule qui doive être
défendue en soutenance.

**Le juge propre ne classe pas mieux que TF-IDF.** Son AUC est **0,772** contre **0,776**
pour TF-IDF et **0,787** pour les embeddings distants : sur l'ordonnancement des énoncés,
les trois sont indiscernables. Payer 0,13 $ n'achète pas un meilleur classement.

**Ce qu'il achète est un point de fonctionnement.** À rappel strictement identique :

| | signalements | VP | FP | FN | P | R | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| (a) TF-IDF | 50 / 139 | 33 | **17** | 22 | 0,660 | 0,600 | 0,629 |
| (c) embeddings | 58 / 139 | 36 | 22 | 19 | 0,621 | 0,655 | 0,637 |
| **(d) juge propre** | 37 / 139 | 33 | **4** | 22 | **0,892** | 0,600 | 0,717 |
| (d⁻) juge fuité | 53 / 139 | 44 | 9 | 11 | 0,830 | 0,800 | 0,815 |
| (d⁰) juge sans rubrique | 93 / 139 | 41 | 52 | 14 | 0,441 | 0,745 | 0,554 |

*(verdict majoritaire des cinq exécutions ; les 4 lignes de juges sont donc des décisions
stables, pas un tirage.)*

Le juge et TF-IDF trouvent **les mêmes 33 positifs sur 55** et manquent les mêmes 22. La
différence est entièrement dans les faux positifs : **4 contre 17 sur 84 négatifs**.

**Significativité — et c'est ici qu'il faut être prudent :** McNemar exact sur les
verdicts majoritaires des cinq exécutions (plus de puissance qu'un McNemar sur un tirage).

| Comparaison (toutes prédictions) | McNemar exact | Verdict |
|---|---:|---|
| **juge propre vs TF-IDF** | **p = 0,0596** | **non significatif à 5 %** |
| juge propre vs embeddings OpenRouter | p = 0,0357 | significatif de justesse |
| juge propre vs MiniLM | p = 0,0032 | significatif |
| juge propre vs majorité par site | p = 0,0091 | significatif |
| juge propre vs règle lexicale à la main | p = 0,0139 | significatif de justesse |
| juge propre vs juge fuité | p = 0,238 | voir ci-dessous |
| TF-IDF vs embeddings OpenRouter | p = 0,832 | indiscernables |
| TF-IDF vs MiniLM | p = 0,121 | indiscernables |
| TF-IDF vs majorité par site | p = 0,296 | indiscernables |

Le McNemar global mêle deux questions distinctes — « qui trouve plus de positifs ? » et
« qui se trompe moins sur les négatifs ? ». Quand deux approches ont exactement le même
rappel, seule la seconde a un sens :

| Comparaison restreinte | discordances | McNemar exact |
|---|---:|---:|
| juge propre vs TF-IDF, sur les **84 négatifs** | 16 / 3 | **p = 0,0044** |
| juge propre vs TF-IDF, sur les 55 positifs | 11 / 11 | p = 1,000 |
| juge propre vs embeddings, sur les **84 négatifs** | 20 / 2 | **p = 0,0001** |
| juge propre vs embeddings, sur les 55 positifs | 10 / 13 | p = 0,678 |

Le McNemar propre/fuité ne conclut pas (p = 0,238) : il oppose deux jeux de prédictions
dont **121 sur 139 coïncident**, et à 18 désaccords un test binomial n'a aucune puissance.
Sur les **cinq exécutions**, en revanche, les deux étendues sont disjointes
(0,703–0,717 contre 0,792–0,826) et le test exact de Mann-Whitney donne la plus petite
valeur possible pour 5 contre 5 : **p = 0,0079**. C'est le test à citer.

**Ce que la fuite achetait, exactement : du rappel.** Le juge fuité et le juge propre ont
la même précision à 6 points près (0,830 contre 0,892) mais un rappel très différent
(0,800 contre 0,600). Restreint aux 55 positifs, le McNemar donne **1 / 12 en faveur du
juge fuité, p = 0,0034** ; restreint aux 84 négatifs, il donne 5 / 0 en faveur du juge
propre (p = 0,0625). Autrement dit, les quatre positifs recopiés dans la rubrique
n'ajoutaient pas quatre bonnes réponses : ils faisaient reconnaître **onze positifs
supplémentaires** en enseignant un motif — ce qui est précisément la définition d'une
contamination, et la raison pour laquelle retirer les items fuités ne la mesure pas (§7c).

**Intervalles de confiance sur la précision** (Wilson 95 %) : juge propre 0,892
[0,753 ; 0,957] sur 37 signalements ; TF-IDF 0,660 [0,522 ; 0,776] sur 50. Les deux
intervalles se **chevauchent de peu** (0,753–0,776) : à 139 items, même l'écart de
précision, qui est le résultat le plus net du tableau, n'est pas confortablement établi.
C'est le McNemar apparié restreint aux négatifs (p = 0,0044) qui le soutient, pas la
comparaison de deux intervalles indépendants.

---

## 6. La dégénérescence du seuil (C2), démontrée

| Approche | seuil J (publié) | seuil fixe 0,5 | **seuil max-F1 (ancien critère)** |
|---|---:|---:|---:|
| (a) TF-IDF | 0,629 | 0,627 | 0,636 |
| (c) embeddings | 0,637 | 0,618 | 0,632 |
| (d) juge flash — rubrique propre | 0,715 | 0,715 | 0,715 |
| (d⁰) juge flash — sans rubrique | 0,565 | 0,311 | 0,604 |
| **(e) juge flash-lite — rubrique propre** | **0,245** | 0,235 | **0,567** ← tout positif |
| (e⁻) juge flash-lite — rubrique fuitée | 0,490 | 0,482 | 0,562 |

Le cas (e) est la démonstration exacte du problème : la maximisation du F1 attribue à un
détecteur dont l'AUC vaut 0,551 un F1 de **0,567**, qui est **au millième la ligne « tout
positif »**. Le J de Youden lui attribue 0,245. Un jury qui compare les colonnes 1 et 3
voit immédiatement lequel des deux critères ment.

**Corollaire — la phrase du 15/08 sur `flash-lite` était fausse, mais dans l'autre sens.**
Le dossier écrivait « `gemini-2.5-flash-lite` s'effondre au niveau du hasard » ; la
vérification a répondu, à juste titre, que son AUC de 0,649 était au-dessus du hasard.
Avec une rubrique propre, son AUC tombe à **0,551**. La phrase d'origine devient donc
vraie — mais pour une raison qu'aucun des deux dossiers n'avait vue : c'était la fuite qui
maintenait le petit modèle au-dessus du hasard.

---

## 7. Ce que la correction ne corrige pas — les réserves obligatoires

**(a) La fuite structurelle demeure, et elle est plus grande que la fuite verbatim.** Le
même modèle, sur le même corpus, **sans** rubrique, obtient F1 0,565 ± 0,024 — soit la
valeur de la ligne « tout positif » (0,567), avec 52 faux positifs sur 84 négatifs. La
grille transmise vaut donc **+0,150 de F1** (McNemar p < 10⁻⁴), c'est-à-dire davantage que
la fuite verbatim (+0,095). Le protocole mesure la **reproductibilité d'une grille
d'étiquetage entre deux modèles**, et non la détection de l'ambiguïté. Aucune réécriture
de prompt ne peut lever cette limite : retirer la grille, c'est mesurer autre chose.

**(b) L'annotateur est un LLM, unique, sans second annotateur.** Il n'existe **aucune
vérité terrain humaine** pour T5. Le κ inter-annotateurs est non mesurable. La
recommandation du rapport 4 — faire ré-étiqueter 40 tâches par un humain et publier le κ —
reste la seule voie de sortie, et elle n'a pas été suivie.

**(c) Retirer les items fuités ne mesure pas la fuite.** La vérification adverse estimait
l'effet à **−0,016** en retirant les quatre énoncés du calcul. La bonne mesure — refaire
tourner le juge avec une rubrique propre — donne **−0,095**, six fois plus. La raison est
mécanique : les exemples fuités n'enseignaient pas quatre items, ils enseignaient un
*motif* qui se transfère aux autres. Sur les 134 tâches restantes, l'écart propre/fuité est
de 0,094, identique à celui mesuré sur 139.

| | F1 sur 139 | F1 sur 134 (hors items fuités) |
|---|---:|---:|
| (d) juge propre | 0,715 ± 0,006 | 0,703 ± 0,007 |
| (d⁻) juge fuité | 0,810 ± 0,012 | 0,797 ± 0,015 |
| écart | **0,095** | **0,094** |

**(d) L'enseignement qualitatif du rapport 4 est réfuté.** Rappel par critère
(verdict majoritaire des cinq exécutions) :

| Critère | n | TF-IDF | embeddings | **juge propre** | juge fuité | juge sans rubrique |
|---|---:|---:|---:|---:|---:|---:|
| A1 multiplicité | 38 | 84 % | 92 % | **63 %** | 84 % | 74 % |
| A2 critère subjectif | 9 | 44 % | 56 % | **100 %** | 100 % | 89 % |
| **A3 référent indéterminé** | 10 | 10 % | 10 % | **30 %** | **70 %** | 90 % |
| A4 sortie indéterminée | 9 | 33 % | 33 % | **78 %** | 67 % | 67 % |
| faux positifs | 84 | 17 | 22 | **4** | 9 | 52 |

Le rapport 4 annonçait « A2 1,00 · A3 0,80 » et illustrait A3 par *« seul le juge voit
"the latest iPad model" (référent flou) »*. Avec une rubrique propre, **A3 tombe de 70 % à
30 %** — et le juge propre manque précisément `Apple--11`, l'exemple cité. La supériorité
sur A3 était la fuite ; celle sur A2 (100 %, et encore 89 % sans aucune rubrique) survit,
mais A2 ne compte que 9 items et se réduit à la présence d'un adjectif d'appréciation, que
la règle lexicale écrite à la main attrape déjà 6 fois sur 9.
A4 (78 % contre 33 %) est le seul avantage qualitatif du juge qui soit à la fois net et
non contaminé — sur 9 items.

**(e) Tous les effectifs sont petits.** 139 items, 55 positifs, 9 ou 10 items par critère
A2/A3/A4. Aucun résultat par critère n'est significatif isolément ; ils sont donnés comme
description, pas comme mesure.

**(f) La variance inter-exécutions du juge propre est faible mais non nulle.** Le taux de
bascule de verdict au seuil 0,5 est de **0,7 %** sur cinq exécutions (contre 4,3 % pour la
rubrique fuitée et 5,8 % pour `flash-lite`). À température 0, un juge n'est pas une
fonction — mais avec cette rubrique-ci, il en est proche.

**(g) La carte de santé publiée n'a pas été régénérée.** Les 238 constats T5 de
`runs/health_20260815.json` ont été produits avec la rubrique fuitée. Ils doivent être
soit recalculés, soit cités avec la mention explicite du prompt utilisé. Le fichier
`benchmark_doctor/detectors/l3_client.py` porte encore, en commentaire de
`DEFAULT_CHAT_MODEL`, les chiffres périmés « F1 0,827 » et « s'effondre au niveau du
hasard, AUC 0,649 » : **à corriger avant le dépôt**.

---

## 8. Les phrases à écrire dans le mémoire

Formulations exactes, à substituer aux affirmations du 15/08.

1. **À la place de** « le juge LLM détecte l'ambiguïté à F1 0,83 » :
   > « Un juge `gemini-2.5-flash` reproduit notre grille d'annotation avec un F1 hors plis
   > de **0,715 ± 0,006** sur cinq exécutions indépendantes (validation croisée à 5 plis,
   > 139 énoncés, seuil calibré par le J de Youden ; le F1 au seuil fixe 0,5 est
   > identique). Ce chiffre reste une **borne haute** : les étiquettes sont produites par
   > un LLM, la grille d'étiquetage est transmise au juge, et le même juge privé de cette
   > grille retombe à F1 0,565 — la valeur de la stratégie triviale « tout positif ». Le
   > protocole mesure la reproductibilité d'une grille entre deux modèles, non la
   > détection de l'ambiguïté. »

2. **À la place de** « le juge bat les approches gratuites » :
   > « À rappel identique (0,60), le juge produit **4 faux positifs sur 84 négatifs contre
   > 17** pour une régression logistique sur TF-IDF (McNemar restreint aux négatifs,
   > p = 0,0044) ; sa précision est de 0,89 [IC95 0,75 ; 0,96] contre 0,66 [0,52 ; 0,78].
   > Son AUC (0,772) est en revanche celle de TF-IDF (0,776) : il **n'ordonne pas mieux**
   > les énoncés, il décide à un meilleur point de fonctionnement. Sur le F1 global,
   > l'écart entre les deux n'est pas significatif à 5 % (p = 0,0596). »

3. **Sur la fuite elle-même** (à assumer, c'est un résultat) :
   > « Notre première mesure attribuait au juge un F1 de 0,827. Une vérification adverse a
   > établi que la rubrique transmise au juge contenait cinq énoncés du jeu d'évaluation,
   > dont quatre positifs. Rubrique réécrite avec des exemples fabriqués et vérifiés hors
   > corpus, le F1 tombe à 0,715 (Mann-Whitney exact sur 5 exécutions contre 5,
   > p = 0,0079). Nous publions le chiffre corrigé. Retirer simplement les cinq énoncés du
   > calcul n'aurait fait perdre que 0,016 point : **une fuite de prompt ne se corrige pas
   > en retirant les items fuités, elle se corrige en refaisant la mesure.** »

4. **Sur le modèle bon marché** :
   > « Avec `gemini-2.5-flash-lite`, quatre fois moins cher, le juge atteint F1 0,245 et
   > **AUC 0,551** : il est au niveau du hasard. La performance d'un juge LLM n'est pas
   > monotone en fonction de son prix. »

5. **Sur la calibration** :
   > « Un seuil calibré par maximisation du F1 dégénère : à 39,6 % de prévalence, la
   > stratégie « tout positif » vaut déjà F1 0,567, et le critère la sélectionne dès que le
   > classifieur est faible — c'est exactement ce qui arrive à `flash-lite`, à qui il
   > attribue 0,567 quand le J de Youden lui attribue 0,245. Nous calibrons sur le J de
   > Youden et publions le tableau au seuil fixe 0,5 en regard. »

6. **Sur le backend par défaut** (C13) :
   > « Le backend `tfidf` est entraîné sur les 139 tâches annotées puis appliqué aux 643 :
   > sa précision apparente sur l'intersection est de 0,964, sa précision hors plis de
   > 0,660. Seule la seconde est publiée, et aucune carte de santé produite avec ce backend
   > n'est citée comme mesure. »

---

## 9. Reproduire

```bash
python experiments/check_rubric_leak.py --both        # 0 $, ~2 s
python experiments/ablation_l3_clean.py               # 0 $ après cette campagne
python experiments/render_ablation_l3.py              # les tableaux ci-dessus
python experiments/analyse_ablation_l3.py             # significativité, critères, fuite
```

Les 2 224 appels facturés de cette campagne rejoignent dans `runs/l3_cache/` les 1 251 qui
y étaient déjà : la ré-exécution est gratuite et hors ligne. Un tiers **sans** ce cache
re-appellerait l'API et obtiendrait des chiffres à 1 ou 2 % près (taux de bascule mesuré :
0,7 % au seuil 0,5 pour la rubrique propre).

**Détail du coût réel** (`usage.cost`, 16/08/2026) :

| Famille | Appels facturés | Servis par le cache | Coût |
|---|---:|---:|---:|
| (d) juge flash, rubrique propre, 5 exéc. | 695 | 0 | 0,13524 $ |
| (d⁻) juge flash, rubrique fuitée, 5 exéc. | 139 | 556 | 0,02837 $ |
| (d⁰) juge flash, sans rubrique, 5 exéc. | 556 | 139 | 0,05969 $ |
| (e) juge flash-lite, rubrique propre, 5 exéc. | 695 | 0 | 0,03961 $ |
| (e⁻) juge flash-lite, rubrique fuitée, 5 exéc. | 139 | 556 | 0,00729 $ |
| (c) embeddings `text-embedding-3-small` | 0 | 3 lots | 0,00000 $ (première mesure : 0,00007 $) |
| **Total** | **2 224** | **1 251** | **0,27020 $** |

Les 556 appels servis par le cache dans la ligne (d⁻) sont les quatre exécutions déjà
présentes dans `runs/l3_cache/` : la moitié de la comparaison avant/après n'a rien coûté,
et la reconstruction du prompt du 15/08 est validée par le fait même qu'elle **touche le
cache à 139/139** sur chacune de ces quatre variantes.
