# Vérification adverse de `benchmark-doctor`

**Date** : 16/08/2026
**Périmètre** : tout le dépôt `/home/user/memoirem2/benchmark-doctor`, les artefacts de
`runs/`, `data/`, `exports/`, `figures/`, `docs/` et le `README.md`.

Toutes les commandes ci-dessous ont été exécutées dans `/home/user/memoirem2/benchmark-doctor`
avec le Python du système (3.11.15) et le paquet installé en mode éditable. Aucune dépense
d'API : le cache `runs/l3_cache/` a servi les 782 appels LLM nécessaires (coût total
0,00000 $, vérifié par le compteur `CostLedger`).

## 1. Les trois problèmes bloquants

### B1. Fuite du jeu de test dans le prompt du juge L3 (fuite, gravité maximale)

Le rapport 4 présente comme résultat central : *« le juge `gemini-2.5-flash` atteint F1 0,827 ±
0,058 »*, et comme enseignement qualitatif : *« seul le juge voit "the latest iPad model"
(référent flou) et "the best podcasts" (subjectif) »*.

La rubrique passée au juge (`_RUBRIC`, `benchmark_doctor/detectors/l3_ambiguity.py`)
contient **quatre énoncés du jeu d'évaluation, recopiés mot pour mot**, tous étiquetés 1 :

```
$ python3 -c "
import json
p=json.load(open('data/annotations_ambiguity.json'))['items']
for ph in ['latest iPad','renowned university','innovative and widely recognized','at least 500 stars']:
    for i in p:
        if ph.lower() in i['question'].lower(): print(f'{ph!r:38s} -> {i[\"task_id\"]:16s} label={i[\"label\"]} criteres={i[\"criteria\"]}')
"
'latest iPad'                          -> Apple--11        label=1 criteres=['A3']
'renowned university'                  -> Coursera--0      label=1 criteres=['A1', 'A2']
'innovative and widely recognized'     -> Huggingface--23  label=1 criteres=['A2', 'A4']
'at least 500 stars'                   -> GitHub--5        label=1 criteres=['A1']
```

Extrait de la rubrique (`l3_ambiguity.py`) :

> `- several items satisfy the stated filters and nothing selects one of them`
> `  ("find a hotel rated above 8.0", "a Python repo with at least 500 stars");`
> `- the selection criterion is subjective … ("best", "popular", "renowned university",`
> `  "innovative and widely recognized");`
> `- the referent or the category is not determined ("the latest iPad model" …)`

Ces quatre items couvrent **2 des 9 positifs A2** et **1 des 10 positifs A3**, précisément les
deux sous-catégories où le rapport 4 annonce la supériorité du juge (« A2 1,00 · A3 0,80 »).

L'effet numérique est modeste (F1 0,804 → 0,788 en retirant les 4 items ; mesuré ci-dessous),
mais **l'affirmation qualitative est réfutée** : le juge ne « voit » pas *the latest iPad model*,
il le lit dans son propre prompt.

```
$ python3 …   # scores servis par le cache, 0 appel réseau
TOUS (n=139)       P0.827 R0.782 F10.804 tp43 fp9 fn12
hors 4 fuites(135) P0.812 R0.765 F10.788 tp39 fp9 fn12
   Coursera--0      label=1 score=1.0
   Apple--11        label=1 score=0.5
   Huggingface--23  label=1 score=1.0
   GitHub--5        label=1 score=1.0
```

**Le problème structurel est plus large que ces quatre phrases.** L'unique annotateur est un LLM ;
la rubrique du juge est la transcription de la grille d'annotation (le code le dit lui-même :
*« ``rubric`` lui transmet la même définition que celle de l'annotateur — … c'est la seule
approche qui reçoit la grille d'étiquetage »*, `l3_ambiguity.py`). Le prompt contient
aussi les contre-exemples négatifs *« a dictionary word, a named repository, a named course, a
fully specified product configuration, a computation »*, qui décrivent exactement les sites sans
aucun positif dans le jeu (Cambridge Dictionary, ArXiv, ESPN).

Le F1 0,827 ne mesure donc pas « la détection de l'ambiguïté » : il mesure **l'accord entre deux
LLM appliquant la même grille, dont l'un a reçu des exemples tirés du corpus d'évaluation**. La
comparaison avec TF-IDF est structurellement déloyale : TF-IDF apprend sur 111 exemples par pli,
le juge reçoit une grille écrite en connaissance des 139.

**Correction recommandée** (par ordre de coût croissant) :
1. **Obligatoire, coût nul** : réécrire la rubrique en remplaçant les quatre exemples par des
   énoncés fabriqués, hors corpus, et re-mesurer. C'est un appel de 0,03 $ et une heure.
2. **Obligatoire, coût nul** : dans le mémoire, ne jamais écrire « le juge détecte l'ambiguïté à
   F1 0,83 » mais « le juge reproduit la grille d'annotation à F1 0,83, grille qu'il a reçue et
   dont quatre exemples proviennent du jeu évalué ; c'est une borne haute optimiste ».
3. **Recommandé** : faire ré-étiqueter 40 tâches par un humain et publier le κ. La proposition
   existe déjà ; sans cela il n'existe **aucune** vérité terrain humaine pour T5.

### B2. La précision de 0,986 de L1 est intégralement in-sample

Le tableau de validation (rapport 6, `README.md`, `docs/METHODOLOGY.md`) affiche :

> `L1 (73 flags)  0,986/0,426/0,595` contre `signalee_1` (169 tâches, « 6 annotateurs indépendants »)

Cette colonne est présentée comme une validation **contre six annotateurs**, donc plus large que
Magnitude. C'est faux. Sur les 72 vrais positifs, **71 sont des tâches Magnitude**, le patch-set
sur lequel les détecteurs ont explicitement été réglés. L'apport des
cinq autres annotateurs à cette précision est **une tâche** :

```
$ python3 …  # data/ground_truth.json + runs/health_20260815_findings.json
signalee_1: 169 magnitude: 121
L1 HIGH flags: 73
TP vs signalee_1: 72   TP vs magnitude: 71
TP apportés par un annotateur AUTRE que Magnitude: 1 ['Amazon--5']
```

J'ai donc construit le hors-échantillon que le dépôt ne contient pas : les **522 tâches que
Magnitude n'a jamais touchées**, avec pour vérité « signalée par au moins un des cinq autres
annotateurs » (48 positifs, prévalence 9,2 %).

```
config    seuil   flags   TP       P   lift      R         p(binomial unilatéral)
L1        high        2    1   0.500   5.44  0.021     0.175   <-- non significatif
L1        medium     49   16   0.327   3.55  0.333  4.49e-06   <-- le seul résultat solide
L2        high      126   18   0.143   1.55  0.375    0.0404
L3        high       67   12   0.179   1.95  0.250    0.0183
L1+L2     high      127   18   0.142   1.54  0.375    0.0431
L1+L2+L3  high      177   26   0.147   1.60  0.542    0.0117
L1+L2+L3  medium    313   40   0.128   1.39  0.833    0.0217
```

**Lecture** : hors du patch-set d'ajustement, `L1` au seuil HIGH ne signale que **2 tâches sur
522**, dont 1 correcte. La « précision de 97 % » n'existe qu'à l'intérieur du corpus qui a servi à
la produire. Le seul résultat qui survive hors échantillon est **L1 au seuil MEDIUM** :
P = 0,327 contre 0,092 attendu au hasard, lift 3,55, p = 4,5·10⁻⁶.

**Correction recommandée** : publier cette table en regard de celle du rapport 6 et faire de
**L1/MEDIUM le résultat de référence du mémoire**, en écrivant que L1/HIGH est un régime de
très haute précision non validable hors échantillon faute de flags. Le code de la table est
reproductible en dix lignes à partir de `data/ground_truth.json` et
`runs/health_20260815_findings.json`.

### B3. Convergence et Magnitude ne sont pas deux annotateurs indépendants

Le rapport 2 fonde tout son appareil statistique sur « **6 annotateurs distincts** » : κ de Fleiss,
matrice de désaccord, `signalee_1/3/6`, courbe longitudinale A. J'ai testé l'hypothèse
d'indépendance en comparant, tâche à tâche, le **texte** des réécritures :

```
$ python3 …  # paires de sources ayant réécrit la même tâche, égalité de chaîne
convergence   |magnitude      identiques  56/ 60      <-- 93 %
fara          |magnitude      identiques  10/ 64
alumnium      |skyvern_2026   identiques   5/ 69
browseruse    |magnitude      identiques   2/ 63
… toutes les autres paires : 0 à 3 sur ~65
```

Exemples (identiques au caractère près) :

```
Booking--5   ORIG : … in Bali from Jan 1 to Jan 4, 2024.
             CONV : … in Bali from Jan 1 to Jan 4, 2026.
             MAGN : … in Bali from Jan 1 to Jan 4, 2026.
Booking--8   CONV = MAGN : « … in Chennai for 20/12/2025 - 21/12/2025. »
```

Convergence est daté du 17/02/2025, Magnitude du 06/07/2025 : la filiation va de l'un vers
l'autre (ou depuis une source commune). Ce sont **deux votes pour un jugement**.

Effet quantifié, en fusionnant les deux sources en un annotateur (action la plus sévère des deux) :

```
Fleiss 3 cat.  6 annotateurs : 0.7371   →  5 annotateurs : 0.7237
Fleiss exclusion              0.5136   →                  0.4682
signalee_3 (majorité)            123   →                     119
unanime                           68   →                      73
```

L'effet sur le κ est faible (≈ 1 point) : le chiffre 0,737 n'est pas à jeter.
Mais trois affirmations du dossier deviennent fausses ou fragiles :

1. « **6 annotateurs distincts** » et « κ de Fleiss applicable car n constant = 6 » : l'hypothèse
   d'échangeabilité **et** d'indépendance est violée de façon démontrable, pas seulement
   « discutable en principe » comme l'écrit la limite du rapport 2.
2. « `signalee_1` = signalée par au moins 1 des **6 annotateurs indépendants** » : la description
   figure telle quelle dans `runs/validation_ablation_20260815.json`
   (`"description": "signalée … par au moins 1 des 6 annotateurs indépendants"`). Le mot
   *indépendants* doit sauter.
3. Le κ pairé `convergence|magnitude` = 0,857 est présenté comme un accord ; c'est une copie.

**Correction recommandée** : (a) supprimer le mot « indépendants » partout ; (b) ajouter une
phrase dans le chapitre méthode : *« Convergence et Magnitude partagent 56 de leurs 60 réécritures
communes au caractère près : nous les traitons comme deux jalons datés d'une même lignée, et nous
publions le κ dans les deux conventions (0,737 à six voix, 0,724 à cinq) »* ; (c) vérifier
symétriquement si l'un des deux dépôts cite l'autre, ce que je n'ai pas fait faute de sources
distantes.

## 2. Problèmes à corriger

### C1. Le F1 0,827 du juge est le meilleur de quatre exécutions

Le cache contient quatre exécutions indépendantes du même juge, même prompt, même température 0
(variantes `None`, `v1`, `v2`, `v3`). Toutes servies sans appel réseau :

```
$ python3 …
variant=None  appels_reseau=  0  P=0.827 R=0.782 F1=0.804 (tp43 fp9 fn12)
variant=v1    appels_reseau=  0  P=0.833 R=0.818 F1=0.826 (tp45 fp9 fn10)
variant=v2    appels_reseau=  0  P=0.830 R=0.800 F1=0.815 (tp44 fp9 fn11)
variant=v3    appels_reseau=  0  P=0.824 R=0.764 F1=0.792 (tp42 fp9 fn13)

F1 entre exécutions : [0.804, 0.826, 0.815, 0.792]  étendue = 0.033
coût réel de cette vérification : 0.00000 $
```

Le tableau principal publie **0,827 ± 0,058**, c'est-à-dire la valeur de `v1`, le maximum des
quatre, assortie d'un écart-type **inter-plis**. L'écart-type **inter-exécutions** (≈ 0,015,
étendue 0,033) n'apparaît nulle part, alors que le rapport 4 mesure bien le taux de bascule
(2,2 %) sans jamais le convertir en incertitude sur le F1.

**Correction** : publier « F1 = 0,81 ± 0,02 (4 exécutions) » ou, mieux, « médiane 0,81, étendue
0,79–0,83 sur 4 exécutions », et réserver le ± 0,058 à la variabilité entre plis, en le nommant.
Sans cela, l'écart annoncé de 31 points entre `flash-lite` et `flash` reste vrai, mais l'écart de
7 points entre `flash` (0,827) et `haiku-4.5` (0,758) devient beaucoup moins net qu'il n'y paraît,
alors qu'il est déclaré significatif par McNemar (p = 0,0127) sur **une seule** exécution de
chaque.

### C2. Le seuil « calibré par maximisation du F1 » dégénère en tout-positif

Trois lignes du tableau principal sont, à la lecture du JSON, la ligne « tout positif » déguisée :

```
$ python3 …   # runs/ablation_ambiguity_20260815.json
always_positive     F1 0.567  pooled tp=55 fp=84 fn=0 tn=0
d_llm_judge_rubric  F1 0.567  pooled tp=55 fp=84 fn=0 tn=0   <-- identique
heuristic           F1 0.501  pooled tp=46 fp=71 fn=9 tn=13
```

Avec une prévalence de 39,6 %, la stratégie « tout positif » obtient F1 = 0,567. Un critère de
seuil qui **maximise le F1** sélectionne donc mécaniquement cette dégénérescence dès que le
classifieur est faible. Le classement publié en dépend : au seuil fixe 0,5, la « règle lexicale à
la main » (0,543) **bat** le juge flash-lite rubrique (0,512), alors que le tableau calibré
affiche l'inverse (0,501 contre 0,567).

Corollaire : l'affirmation *« `gemini-2.5-flash-lite` s'effondre au niveau du hasard »* n'est pas
soutenue. Son AUC est 0,649, au-dessus du hasard (0,500). Ce qui s'effondre, c'est le couple
(scorer faible, seuil maximisant le F1).

**Correction** : (a) calibrer sur le J de Youden ou la balanced accuracy, pas sur le F1 ; ou
(b) publier le tableau au seuil fixe 0,5 comme tableau principal (c'est déjà ce que fait la
figure 5, ce qui crée une incohérence entre la figure et le texte) ; (c) remplacer « au niveau du
hasard » par « à l'AUC 0,65, avec un seuil qui dégénère ».

### C3. Aucune ligne de base « hasard », et une colonne entière non significative

Le tableau de validation publie P/R/F1 pour 6 configurations × 5 vérités × 2 seuils, sans jamais
donner la précision attendue au hasard (= la prévalence de la vérité). J'ai ajouté cette colonne
et un test binomial unilatéral :

```
config    seuil   flags  GT                P  P_hasard   lift      R  p_unilat
L1        high       73  supprimee_1   0.164     0.121   1.36  0.154      0.17   <-- NON SIGNIFICATIF
L2        high      175  supprimee_1   0.143     0.121   1.18  0.321     0.221   <-- NON SIGNIFICATIF
L2        high      175  signalee_1    0.383     0.263   1.46  0.396  0.000339
L1+L2     high      214  supprimee_1   0.149     0.121   1.23  0.410     0.124   <-- NON SIGNIFICATIF
L3        medium    325  supprimee_1   0.129     0.121   1.07  0.538     0.355   <-- NON SIGNIFICATIF
L1+L2+L3  medium    424  supprimee_1   0.149     0.121   1.22  0.808    0.0529   <-- NON SIGNIFICATIF
L1+L2+L3  medium    424  signalee_1    0.356     0.263   1.35  0.893  1.45e-05
```

Deux conséquences.

1. **Contre `supprimee_1`, la vérité la plus proche de « la tâche est morte », l'outil n'est
   significativement meilleur que le hasard dans aucune configuration au seuil HIGH.** Le dossier
   présente cette colonne comme un simple « effondrement de la précision selon la vérité retenue »
   (0,986 → 0,164) sans dire qu'il s'agit d'un résultat nul.
2. Les rappels spectaculaires du seuil MEDIUM (0,89 à 0,99) sont largement mécaniques : `L1+L2+L3`
   au seuil MEDIUM signale **424 tâches sur 643 (66 %)**. Un tirage au hasard de 424 tâches
   obtiendrait déjà un rappel de 0,66. Le lift réel est de 1,35.

**Correction** : ajouter systématiquement les colonnes « précision au hasard » et « lift » à la
grille 5 × 2, et écrire noir sur blanc que la colonne `supprimee_1` est un résultat nul. C'est
défendable en soutenance (« nos détecteurs voient ce qui *se périme*, pas ce que les praticiens
*décident de retirer* ») ; le passer sous silence ne l'est pas.

### C4. Dénominateur incohérent dans la table des sept forks

`README.md` et `analysis_longitudinal.py` :

| Fork | n publié | corpus réel du fork |
|---|---:|---:|
| browser-use | **643** | **588** (643 − 55 exclusions) |
| Skyvern 01/2025 | 635 | 635 (après exclusions) |
| Magnitude | 590 | 590 (après exclusions) |
| Fara | 595 | 595 |
| Alumnium | 619 | 619 |

`browseruse_tasks.jsonl` contient **encore les 55 tâches que browser-use a lui-même déclarées
impossibles** (`browseruse_impossible.json`) ; le loader `loaders.py` les traite bien comme
`remove`, mais `forks_health()` charge le fichier brut.

```
$ python3 …
impossible ids présents dans browseruse_tasks.jsonl : 55
browser-use 643 (tel quel)       n= 643  naissance  12 (1.9%)  15/08/2026  72 (11.2%)
browser-use 588 (corpus réel)    n= 588  naissance   3 (0.5%)  15/08/2026  62 (10.5%)
```

**Neuf des douze flags « à sa naissance » sont des tâches que browser-use avait déjà supprimées.**
Le chiffre publié (1,9 %) est près de quatre fois le vrai (0,5 %) ; il affaiblit d'ailleurs
l'argument du mémoire (« un fork naît sain puis se dégrade ») au lieu de le renforcer.

**Correction** : dans `FORKS`, charger `browseruse_tasks.jsonl` **moins** les 55 identifiants de
`browseruse_impossible.json`, et republier la ligne : `browser-use | 2024-12-15 | 588 | 3 (0,5 %)
| 62 (10,5 %)`. Une ligne de code.

### C5. « Prévalence par catégorie » est un taux de signalement, pas une prévalence

`README.md` titre « Prevalence by taxonomy category ». Un jury lira « 37,3 % des tâches de
WebVoyager sont ambiguës ». Or ces chiffres sont des **taux de flag de détecteurs dont la
précision va de 0,26 à 1,00 et n'est validée que pour deux catégories sur huit**.

Inventaire complet des constats de la carte (`runs/health_20260815_findings.json`) :

```
('l1_temporal', 'relative_date', 'low')            146     <-- 90 % de T7
('l1_temporal', 'yearless_date_transactional','medium') 17
('l1_reference','named_content','low')              92     <-- 53 % de T2
('l1_reference','versioned_product','medium')       35
('l1_reference','plan_or_tier','medium')             3
('l3_ambiguity', …,'medium')                       238     <-- 100 % de T5
('l2_liveness','ok','info')                        428
```

Deux cas sont indéfendables tels quels :

- **T7 « fragilité d'évaluation » : 163 tâches (25,3 %)**, dont 146 proviennent d'un unique regex
  de vingt mots-clés (`RELATIVE_DATE_RE`, `l1_temporal.py` : `latest|current|recent|
  upcoming|today|…`), émis en `LOW` avec une confiance de 0,50. **Aucune vérité terrain n'existe
  pour T7** : la relecture manuelle des 121 raisons Magnitude donne T7 = 0 en catégorie
  principale, et la table « rappel par catégorie » du rapport 6 n'a pas de ligne T7. C'est la
  deuxième catégorie du tableau, et elle n'est adossée à rien. Échantillon de faux positifs
  évidents : `ArXiv--19` (« Which university maintains and manages ArXiv … currently »),
  `Google Search--19` (« Bert's latest commit »).
- **T2 « dérive de contenu » : 187 tâches (29,1 %)**, dont 130 constats viennent de
  `l1_reference`, que sa propre docstring et le rapport 1 qualifient de *« proxy, un outil de tri
  pour L2, pas un détecteur »*, et dont la précision mesurée est **0,421** avec un rappel « bonne
  catégorie » de **4/21**.

**Correction** : renommer la colonne « Tasks » en « tâches portant au moins un signal » (le README
le dit déjà en légende, mais le titre du tableau dit « Prevalence »), ajouter une colonne
« précision mesurée du détecteur émetteur, et contre quelle vérité », et marquer T7 d'une note
explicite : *« aucune vérité terrain disponible ; ce chiffre est un taux de signalement, pas une
prévalence »*. Sans cela, c'est le chiffre le plus facilement attaquable du mémoire.

### C6. `diff_channel_artifact` : « seul le canal change » est faux

Le rapport 5 décrit ce différentiel comme *« même corpus, 1 jour d'écart, seul le canal change
(navigateur cloud → HTTP datacenter) »* et en tire 127 dégradations.

En réalité, la carte « navigateur cloud » ne repose que sur **4 URL réellement mesurées** ; les
onze autres sites sont classés `unreachable`, signature dont `is_site_verdict` est faux et dont le
risque est nul, donc note A par défaut.

```
$ python3 …
runs/card_browsercloud_20260815.json
   {'l2_liveness (ok)': 89, 'l2_liveness (unreachable)': 500, 'l2_liveness (antibot_challenge)': 41, …}
sites sans mesure navigateur : ['Amazon','Apple','ArXiv','BBC News','Cambridge Dictionary','Coursera',
                                'GitHub','Google Flights','Google Map','Google Search','Huggingface','Wolfram Alpha']
dégradées par site : {'Allrecipes': 45, 'ESPN': 43, 'Amazon': 39}
dégradées appartenant à un site NON MESURÉ au navigateur : 39
```

**39 des 127 « dégradations » (31 %) sont Amazon, site qui n'a jamais été mesuré au navigateur.**
Ce n'est pas un effet de canal, c'est une absence de mesure convertie en note A.

La démonstration du garde-fou de comparabilité reste valide (le rapport refuse d'interpréter), et
c'est un bon résultat. Mais la phrase « seul le canal change » est fausse et sera relevée.

**Correction** : reformuler en *« deux cartes qui diffèrent par le canal **et par la couverture** :
4 sites mesurés au navigateur contre 15 en HTTP direct, deux raisons indépendantes de refuser la
comparaison, et le garde-fou n'en a besoin que d'une »*. Et retirer le chiffre 127 de tout
argumentaire sur la dépendance au canal ; le chiffre défendable reste **4/14 URL divergentes =
28,6 %** de la campagne L2.

### C7. κ = 0,40 : l'unique confirmation est démentie, et l'argument de prudence est inversé

`bdoctor score-model` re-dérive bien la constante (vérifié, sortie identique au JSON publié) :

```
κ — crédibilité d'un constat de blocage
  URL bloquées recoupables avec un navigateur : 3
  blocages confirmés par le navigateur        : 1
  estimateur Laplace (k+1)/(n+2)  → RETENU    : 0.4
    allrecipes.com  direct=paywall_402      navigateur=ok
    booking.com     direct=antibot_challenge navigateur=antibot_challenge   <-- le « confirmé »
    espn.com        direct=antibot_challenge navigateur=ok
```

Le JSON porte lui-même l'aveu : *« Booking compte comme "confirmé" parce que la signature reste un
challenge, **alors que le navigateur l'a en fait résolu** »*. Or le rapport 3 écrit que le
navigateur *« exécute le challenge JS et obtient la vraie page »*. Opérationnellement, les
**trois** blocages sont faux : k = 0/3, κ_Laplace = 1/5 = **0,20**.

Second problème, plus grave que le premier : la justification écrite (*« la lecture la plus
favorable au constat de blocage, donc la plus prudente pour le score »*) est **inversée**. La
table de sensibilité produite par le même script montre qu'un κ plus grand produit **plus** de
tâches mortes :

```
       κ   stabilité ⌀     A     B     C     D
   0.000        0.6801   290   129   171    53
   0.200        0.6592   290   126   165    62
   0.400        0.6377   239   155   180    69     <-- retenu
   1.000        0.5718   239    81   179   144
```

Choisir k = 1 plutôt que k = 0 fait passer de 62 à 69 tâches en note D. Ce n'est pas prudent : le
choix va **dans le sens de la thèse du mémoire** (« le benchmark se dégrade »). C'est exactement le
type de biais qu'un jury cherche.

**Correction** : soit retenir κ = 0,20 en assumant la lecture opérationnelle (« un canal capable
de résoudre le challenge accède au site »), soit garder 0,40 mais **remplacer** la phrase de
prudence par : *« nous retenons la lecture la plus défavorable au site, donc celle qui gonfle le
plus notre propre mesure de décadence ; la sensibilité publiée (62 → 69 tâches en D) borne l'effet
de ce choix »*. Et dans les deux cas, dire en soutenance que la constante repose sur n = 3.

### C8. Trois cartes de santé et deux échelles de notes en circulation

| Source | stabilité ⌀ | A / B / C / D | configuration |
|---|---:|---|---|
| Rapport 5 · `card_direct_20260816.json` | **0,638** (0,671 détecteurs seuls) | 239 / 155 / 180 / 69 | L1+L2+L3, **sans** solvabilité, 16/08 |
| Rapport 6 · `health_20260815.json` · **README** | **0,585** (0,612) | 210 / 138 / 185 / 110 | L1+L2+L3, **avec** solvabilité, 15/08 |
| Rapport 1 (L1 seul) | 0,856 | 509 / 61 / 8 / 65 | L1, échelle **`models.py`** |

Les deux premières reproduisent parfaitement, je les ai vérifiées :

```
$ bdoctor score-model … --layers l1,l2,l3 --l3-backend llm            # sans solvabilité
  tâches multi-catégories : 262 (40.8 %)   changements de note : 83 / 643
  κ=0.400  stabilité 0.6377  A 239 B 155 C 180 D 69        <-- rapport 5 : exact
$ bdoctor score-model … --layers l1,l2,l3 --l3-backend llm --l3-solvability
  tâches multi-catégories : 283 (44.0 %)   changements de note : 119 / 643
  κ=0.400  stabilité 0.5910  A 213 B 138 C 186 D 106       <-- proche du rapport 6 (1 jour d'écart)
```

Ce n'est donc pas une erreur de calcul, mais un **piège de rédaction majeur** : les deux tables de
sensibilité publiées par le rapport 5 (H3 : 262/83 ; κ : 53/62/69/74/144) sont calculées **sans la
couche solvabilité**, alors que le README publie la carte **avec**. Coller « stabilité 0,585 » et
« κ = 1 → 144 tâches en D » dans le même paragraphe serait factuellement faux (avec solvabilité,
c'est 176).

S'y ajoute la double échelle de notes déjà signalée et toujours présente :
`models.TaskVerdict.grade` (0,85 / 0,60 / 0,35) contre `scoring.grade_for` (> 0,75 / 0,50 / 0,25).
Sur la même carte : `{A 239, B 155, C 180, D 69}` contre `{A 219, B 142, C 170, D 112}`.

**Correction** : choisir **une** carte de référence (je recommande celle avec solvabilité, la plus
complète, qui est celle du README et des figures), la nommer explicitement, régénérer les deux
tables de sensibilité dans cette configuration, et unifier l'échelle de notes en modifiant
`models.py` **et** les trois assertions de `tests/test_pipeline_and_cli.py` qui la verrouillent.

### C9. L'export livre 84 énoncés déjà périmés dans son « sous-ensemble exécutable »

`exports/README.md` : *« Sous-ensemble exécutable (`noyau` ∪ `surveiller` ∪ `corriger`) :
**563 tâches** »*. L'export conserve l'énoncé **original** dans le champ `question` et place le
correctif dans `patch_canonique`.

```
$ python3 …
sous-ensemble exécutable: 563
énoncés exportés (sous-ensemble exécutable) portant une date révolue : 84
  répartition : {'corriger': 63, 'noyau': 14, 'surveiller': 7}
dont patch canonique lui-même périmé : 14
```

Autrement dit : **14,9 % du sous-ensemble présenté comme exécutable ne l'est pas**, et 14 de ces
tâches sont dans le `noyau`, le sous-ensemble décrit comme « jamais signalée par personne, à
exécuter ». Les 20 patches canoniques déjà périmés sont bien documentés (je les ai recomptés à
l'identique, liste exacte), mais le chiffre 563 ne l'est pas.

**Correction** : publier « 563 tâches, dont 84 (14,9 %) dont l'énoncé porte une date révolue au
15/08/2026 : 479 sont exécutables sans retouche ». C'est un résultat en soi, et il renforce la
thèse au lieu de l'affaiblir.

### C10. Couverture de test réelle : 0 % sur 13 848 lignes

Le dossier répète « les 89 tests existants passent toujours » comme signal de qualité.
Mesure :

```
$ python3 -m coverage run -m pytest -q && python3 -m coverage report
benchmark_doctor/detectors/l1_reference.py       25      0   100%
benchmark_doctor/detectors/l1_sideeffect.py      27      0   100%
benchmark_doctor/detectors/l1_temporal.py       176     19    89%
benchmark_doctor/models.py                      241     14    94%
benchmark_doctor/cli.py                         560    386    31%
TOTAL                                          1104    421    62%
```

Les modules **absents du rapport ne sont même pas importés** par la suite de tests :
`scoring.py` (1 332 l.), `report.py` (1 208 l.), `channels.py` (783 l.), `l2_liveness.py` (777 l.),
`l2_campaign.py`, `l2_content.py`, les trois modules L3, les six modules `ground_truth/`,
`run_all.py` (1 059 l.), `analysis_longitudinal.py` (1 180 l.), `experiments/`, `figures/`.
**Total non couvert : 13 848 lignes.**

Concrètement, ne sont testés ni la formule de score, ni la dérivation de κ et λ, ni le garde-fou de
comparabilité (le mécanisme le plus original du dépôt), ni la réconciliation des sept patch-sets,
ni le classifieur anti-bot.

**Correction** : la phrase « 89 tests, tous verts » doit devenir, dans le mémoire comme dans le
README, « 89 tests couvrant la couche L1 et le modèle de données ; les couches L2, L3, le score et
les rapports sont vérifiés par des invariants exécutés à la main et non versionnés ». Et si une
heure est disponible, écrire cinq tests : les neuf invariants du score déjà vérifiés à la main,
et les trois branches du garde-fou de comparabilité.

### C11. Un chiffre du rapport 1 est mesuré sur le mauvais fichier

Rapport 1 : *« Santé L1 comparée des forks au 15/08/2026 : … **Alumnium 03/2026 73/643 (11,4 %)** »*.

`alumnium_tasks.jsonl` est **bit à bit identique** à `webvoyager_original.jsonl` :

```
$ md5sum data/raw/alumnium_tasks.jsonl data/raw/webvoyager_original.jsonl
35fc721997…  data/raw/alumnium_tasks.jsonl
35fc721997…  data/raw/webvoyager_original.jsonl
```

Ce « 73/643 » est donc la mesure du corpus d'origine, étiquetée Alumnium. Le vrai fichier
(`alumnium_patched.jsonl`, 619 tâches) donne **55/619 = 8,9 %**, valeur correctement publiée par
le rapport 6 et le README. Le problème avait été découvert ; le chiffre du rapport 1 n'a
jamais été rétracté.

**Correction** : ne pas reprendre le tableau « santé L1 comparée des forks » du rapport 1. Le
tableau de référence est celui du rapport 6 / `README.md`, après correction de la ligne
browser-use (C4).

### C12. « 87/87 (100 %) de correctifs textuellement différents » : la formulation trompe

Le chiffre est exact **au sens où il est calculé** : pour chacune des 87 tâches réécrites par au
moins deux annotateurs, l'ensemble des variantes compte au moins deux éléments distincts :

```
$ python3 …
n tâches réécrites par >=2 des SIX : 87
toutes variantes identiques        : 0
moyenne réécritures                : 4.93
moyenne variantes DISTINCTES       : 4.00
paires de réécritures identiques   : 92/961 = 9.6 %
```

Mais **9,6 % des paires sont identiques**, et pour la paire Convergence|Magnitude c'est **93 %**
(cf. B3). Écrire « 100 % des correctifs divergent » suggère que deux annotateurs ne s'accordent
jamais ; la vérité est « aucune tâche ne reçoit un correctif unanime ». La différence est
importante quand la lignée Convergence → Magnitude est en cause.

**Correction** : écrire « aucune des 87 tâches ne reçoit un correctif unanime ; 4,0 variantes
distinctes en moyenne pour 4,9 réécritures ». La mesure exigeante, **76/87 = 87,4 % divergent sur
le millésime**, reste la bonne à mettre en avant : elle est robuste.

### C13. Le backend L3 par défaut est in-sample sur 139 des 643 tâches

`build_scorer(fit=True)` entraîne le classifieur sur **la totalité** des 139 annotations
(`l3_ambiguity.py`), puis l'audit le fait scorer les 643 tâches, dont ces 139.

```
$ python3 …
seuil tfidf: 0.5   flags/643: 234
  sur les 139 annotées (in-sample) : 55/139 = 39.6 %
  sur les 504 non annotées         : 179/504 = 35.5 %
  précision apparente in-sample : 53/55 = 0.964   (précision hors plis publiée : 0,654)
```

La carte produite avec le backend par défaut applique donc **deux instruments différents** au même
corpus : un classifieur à 0,96 de précision sur 21,6 % des tâches, à 0,65 sur le reste. Le rapport
5 publie une carte tfidf (stabilité 0,673) et le rapport 6 signale que 45 % des scores changent
entre les deux backends, mais personne ne dit que la carte tfidf est partiellement in-sample.

**Correction** : (a) suivre la recommandation existante (« pour un chiffre publiable, utiliser
`--l3-backend llm` ») et **ne publier aucune carte tfidf** ; (b) si une carte tfidf est publiée,
ajouter dans ses `limits` la phrase « 139 des 643 tâches ont servi à entraîner ce backend ».

## 3. Problèmes mineurs

**M1, λ Online-Mind2Web : biais de temps immortel.** La fenêtre part de la première vague de
remplacement (05/04/2025) mais les 6 tâches de cette vague sont comptées au numérateur. Elles ont
été remplacées *avant* t₀, pas *pendant* la fenêtre.
```
52/300 sur 13.31 mois → λ=0.0143, taux annuel 15.8 %   (publié)
46/300 sur 13.31 mois → λ=0.0125, taux annuel 13.9 %   (hors vague initiale)
```
Effet : 1,9 point sur la « borne supérieure du visible » et 0,0018 sur λ, sans conséquence pratique
(φ = 0,986 à un mois). À signaler dans une note de bas de page, pas à corriger.

**M2, chaîne de documentation périmée dans `scoring.py`.** Le champ `world_decay_source`, recopié
tel quel dans `runs/scoring_model_20260816.json`, annonce « 13,35 mois », « 17 mois », « λ = 0,0180 »,
« demi-vie 39 mois », alors que le même script calcule et affiche 13,31 / 16,59 / 0,01838 / 37,7.
Deux jeux de chiffres pour la même quantité dans le même fichier JSON.

**M3, `runs/l3_cache/` est dans HEAD.** Le `.gitignore` racine ignore
`benchmark-doctor/runs/l3_cache/`, mais les 2 048 fichiers avaient déjà été committés :
```
$ git ls-tree -r HEAD --name-only | grep -c "runs/l3_cache"
2048
```
Un `.gitignore` n'untracke rien. **À noter cependant que c'est ce cache qui rend les chiffres L3
reproductibles hors ligne à 0 $**, je l'ai vérifié (782 appels servis, 0 réseau, 0 $). C'est donc
un choix défendable, mais il doit être **assumé et documenté**, pas subi. Décision à prendre :
`git rm --cached` (et perdre la reproductibilité offline) ou retirer la ligne du `.gitignore` et
documenter le cache comme une donnée du dépôt.

**M4, deux « précisions » construites sur presque rien.** `l2_content` : « précision 1,000,
rappel 0,006 » se calcule sur **un** flag (27 des 28 constats sont des `info` de présence).
`l2_liveness` : « 643 constats » dont **469 sont des `info`** (`ok` ou `channel_blocked`). Dans la
table d'apport marginal, ces deux lignes ne sont pas comparables aux autres. À reformuler en
« 1 constat actionnable sur 28 vérifications » et « 174 constats bloquants sur 643 observations ».

**M5, sur un clone frais les tests de verrouillage se désactivent.** `data/raw/` est gitignoré
(bootstrap par `fetch_sources.py`). Sans données :
```
$ mv data/raw /tmp/… && python3 -m pytest -q
86 passed, 3 skipped in 0.11s
```
Les trois tests qui verrouillent 643 / 121 / 73 / P97 / Booking 33 / Google Flights 33 sont
précisément ceux qui sautent. Un tiers qui clone et lance `pytest` voit « tout vert » sans avoir
rien vérifié. **Correction** : faire échouer, et non skipper, quand `BDOCTOR_REQUIRE_DATA=1`, et
mettre cette variable dans la CI.

**M6, figure 5 sans incertitude.** La figure oppose TF-IDF (0,627) et MiniLM (0,602) comme deux
points distincts, alors que McNemar donne p = 0,405. Ajouter des barres d'étendue inter-plis, ou
une note dans la légende : « les écarts entre (a), (b) et (c) ne sont pas significatifs ». La
figure utilise par ailleurs le F1 au seuil 0,5 quand le tableau utilise le F1 calibré : ce choix
est meilleur que celui du tableau (cf. C2) mais l'écart entre les deux artefacts doit être dit.

**M7, `L2 seuil MEDIUM` ≡ `L2 seuil HIGH`.** `l2_liveness` n'émet que `info` ou `high` ; la ligne
L2 est donc identique dans les deux blocs du tableau (175 / 0,383 / 0,396 / 0,390 dans les deux).
Présenter « deux seuils systématiquement » sans dire que la couche L2 est insensible au seuil
laisse croire à deux mesures là où il n'y en a qu'une.

**M8, `pyproject.toml`.** `probe = ["httpx", "playwright"]` alors que `channels.py` importe
`requests` et `l3_client.py` importe `httpx`. Déjà signalé, toujours non corrigé.
`pip install benchmark-doctor[probe]` ne permet pas d'exécuter la couche L2.

## 4. Ce que j'ai cherché et n'ai pas trouvé

**Normalisation des identifiants entre patch-sets : propre.** Testée sur les sept sources :
```
browseruse_tasks.jsonl        n= 643  doublons=0  hors_corpus=0
skyvern_tasks.jsonl           n= 635  doublons=0  hors_corpus=0
skyvern_tasks_20250116.jsonl  n= 635  doublons=0  hors_corpus=0
fara_webvoyager_20250831.jsonl n= 595 doublons=0  hors_corpus=0
magnitude_patched.jsonl       n= 590  doublons=0  hors_corpus=0
alumnium_patched.jsonl        n= 619  doublons=0  hors_corpus=0
convergence.csv               n= 601  doublons=0  hors_corpus=0
```
Aucune collision, aucun identifiant orphelin, malgré les quatre conventions de séparateur et les
renommages de sites (`GoogleFlights` → `Google Flights`, `Search Engine` → `Google Search`).

**Bornes de dates du détecteur temporel : correctes.** `DateMention.is_past` / `is_future`
(`l1_temporal.py`) : comparaison stricte pour les dates complètes (une tâche datée du jour
même n'est pas périmée), comparaison `(année, mois)` pour les `month_year` (« August 2026 » n'est
ni passé ni futur au 15/08/2026), refus explicite de trancher pour les dates sans millésime,
`try/except ValueError` pour les dates impossibles écrites dans les énoncés. Je n'ai trouvé aucune
erreur de borne, aucun off-by-one, aucun problème de fuseau.

**Les κ sont exacts.** Recalculés à la main depuis `data/ground_truth.json`, sans réutiliser
`stats.py` :
```
Fleiss 3 cat.      : Pobs=0.9192  Pe=0.6928  κ=0.7371   (publié 0,737)
Fleiss exclusion   : Pobs=0.9455  Pe=0.8879  κ=0.5136   (publié 0,514)
Fleiss défaut      :                          κ=0.7651   (publié 0,765)
Cohen extrêmes     : browseruse|magnitude 0.913 (accord brut 0.972) ; browseruse|skyvern_2026 0.619
```
Identiques au chiffre près.

**« Les correctifs pourrissent » : reproduit exactement.** 68 réécritures, 65 datées
(les 3 autres = Apple--4/22/32, changements de produit), **65/65 contiennent une date révolue au
15/08/2026, 0 conserve la moindre date future**. Recompté indépendamment avec
`extract_date_mentions`. C'est le résultat le plus solide du dossier.

**Les 20 patches canoniques périmés : reproduits à l'identique**, liste exacte comprise
(Booking--5/10..18, Amazon--39, Apple--9, ArXiv--15, ESPN--15, GitHub--11/28, Google Flights--9,
Huggingface--0/20, Wolfram Alpha--33).

**Online-Mind2Web : reproduit.** 58 événements, 55 identifiants bruts, **52 tâches distinctes**
après normalisation du suffixe `_051526`, répétitions `{3,2,2,2,2}` : la correction publiée
(quatre tâches remplacées deux fois, une trois fois) est la bonne.

**Reproductibilité des scripts hors ligne : bit à bit.**
```
$ python3 run_all.py --phase validate      → runs/validation_ablation_20260815.json  identique (hors horodatage)
$ python3 analysis_longitudinal.py         → runs/longitudinal_20260815.json          identique (hors horodatage)
$ bdoctor l1-eval …                        → tous les chiffres du rapport 1 reproduits
$ bdoctor score-model … --l3-backend llm   → 262 / 83 / κ{53,62,69,74,144} / A239 B155 C180 D69 : rapport 5 exact
$ python3 figures/make_figures.py --check  → 7 PNG à 300 ppp, 7 PDF vectoriels, contrôle réussi
$ python3 -m pytest -q                     → 89 passed
```

**Amorçage du corpus : vérifiable par un tiers.** J'ai téléchargé l'URL épinglée et recalculé
l'empreinte :
```
$ python3 -c "…MinorJerry/WebVoyager/091544539eba…/data/WebVoyager_data.jsonl"
sha256 69b19fd86c23f1a500244a3724e039aa7ca6a1223d03e11eb10e308d4f11c488   (643 lignes)
attendu (meta.corpus_sha256) : 69b19fd8…c488
```

**Stabilité de la couche L2 à 24 h : confirmée par une mesure nouvelle.** J'ai re-sondé les quinze
URL de départ le 16/08 et comparé aux signatures du 15/08 :
```
Allrecipes paywall_402→paywall_402 · Amazon antibot→antibot · Booking antibot→antibot
ESPN antibot→antibot · GitHub channel_blocked→channel_blocked · les 10 autres ok→ok
signatures changées en 24 h : 0 / 15
```
Le rapport 3 ne revendiquait la stabilité que sur trois minutes ; elle tient à un jour. C'est un
résultat gratuit à ajouter au mémoire.

**Reproductibilité de la carte depuis le cache : exacte.** Les 238 constats T5 de
`health_20260815.json` sont reproduits à l'identique depuis `runs/l3_cache` (différence symétrique
vide, 0 appel réseau). Réserve : un tiers **sans** le cache re-appellerait l'API et obtiendrait
2 à 4 % de constats différents (cf. C1).

**Aucun identifiant de tâche codé en dur dans une décision de détecteur.** `grep -rE
"Site--[0-9]+" benchmark_doctor/detectors/*.py` ne renvoie que des commentaires et des docstrings.
Les corrections apportées sur les faux positifs sont linguistiques (« book » nom contre verbe,
« check out » verbe à particule, négations), pas des exceptions par identifiant. C'est le seul
point qui rend l'ajustement in-sample de B2 défendable en soutenance.

**Aucun secret versionné.** `.env` est ignoré (`.gitignore:1`) et absent de l'index. Le cache L3
ne contient que des réponses d'API, jamais la clé.

## 5. Les cinq phrases à changer dans le mémoire

Par ordre décroissant de risque en soutenance.

1. **« Le juge LLM détecte l'ambiguïté à F1 0,83 »** → *« Un juge LLM reproduit notre grille
   d'annotation à F1 0,81 ± 0,02 sur quatre exécutions. Les étiquettes sont produites par un LLM,
   la grille lui est transmise, et quatre de ses exemples sont tirés du corpus évalué : ce chiffre
   est une borne haute, et le protocole ne mesure pas la détection mais la reproductibilité d'une
   grille entre deux modèles. »*

2. **« Précision 0,986 contre six annotateurs indépendants »** → *« Précision 0,986 mesurée sur un
   ensemble dont 71 des 72 vrais positifs proviennent du patch-set qui a servi à régler les
   détecteurs. Sur les 522 tâches que ce patch-set n'a jamais touchées, la même politique ne
   signale que deux tâches. La configuration qui résiste hors échantillon est L1 au seuil MEDIUM :
   précision 0,33 contre 0,09 attendu au hasard (p = 4,5·10⁻⁶). »*

3. **« Six annotateurs indépendants »** → *« Six patch-sets, dont deux appartiennent à une même
   lignée : Convergence et Magnitude partagent 56 de leurs 60 réécritures communes au caractère
   près. Le κ de Fleiss passe de 0,737 à 0,724 quand on les fusionne. »*

4. **« Prévalence : T5 37,3 %, T2 29,1 %, T7 25,3 % »** → *« Taux de signalement par catégorie.
   T7 (25,3 %) provient à 90 % d'un regex de vingt mots-clés émis en sévérité basse, et aucune
   vérité terrain n'existe pour cette catégorie. T2 (29,1 %) provient à 75 % d'un proxy de
   précision 0,42. Seuls T1 et T5 sont adossés à une mesure de précision. »*

5. **« L'outil complet atteint un rappel de 0,89 »** → *« … en signalant 424 des 643 tâches
   (66 %), soit un lift de 1,35 sur le hasard. Contre la vérité "supprimée par un praticien",
   aucune configuration au seuil HIGH n'est significativement meilleure que le hasard. »*

## 6. Ce que je n'ai pas pu vérifier

- **Les quatre observations « navigateur cloud »** sont saisies à la main dans
  `runs/l2_browser_cloud_20260815.json`. Je n'ai pas pu les reproduire (Browserbase n'est pas
  pilotable depuis le code) ; je n'ai vérifié que leur cohérence interne et leurs limites
  déclarées. **κ, paramètre du score publié, dépend entièrement de ces quatre lignes non
  reproductibles.**
- **La provenance des sept patch-sets** (commits épinglés autres que WebVoyager) : je n'ai vérifié
  par téléchargement que le corpus d'origine. Le sens de la filiation Convergence → Magnitude est
  déduit des dates du dépôt, non d'un historique git consulté.
- **Les 109 raisons reconstituées de l'historique Alumnium** : je n'ai pas rejoué les 20 commits.
- **La relecture manuelle des 121 raisons Magnitude** (`magnitude_reason_labels.json`) : c'est
  l'étiquetage d'un seul agent, sans second annotateur ; il n'est vérifiable par aucune mesure du
  dépôt. Les 16 cas frontaliers sont signalés, mais 12 des 121 étiquettes T1–T8 portent seules
  toute la table « rappel par catégorie ».
- **Le workflow `.github/workflows/weekly.yml`** n'a jamais tourné sur GitHub et je ne l'ai pas
  simulé.
- **Le contenu réel des sites** : aucune vérification manuelle des faux positifs. Les 273 tâches
  que personne n'a jamais signalées et que l'outil note sous A restent indécidées, comme le dit
  l'export.
