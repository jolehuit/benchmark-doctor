# Contre-vérification du 16 août 2026

Le 15 août 2026 j'ai publié une première série de résultats sur `benchmark-doctor`. Le lendemain j'ai repris
chacun d'eux en cherchant ce qui pouvait le faire tomber, en repartant des artefacts de `runs/`, `data/` et
`exports/` plutôt que des rapports qui les commentent. Trois résultats sur quatre en sont sortis modifiés, et
ce sont les valeurs d'après qui sont publiées depuis. Chaque section dit ce que le dépôt affirmait, ce que le
contrôle a mesuré, ce que j'ai corrigé et ce qui reste ouvert. Les campagnes réseau du 15 août n'ont pas été
rejouées : les contrôles portent sur le journal de constats gelé `runs/health_20260815_findings.json`, et la
seule mesure neuve qui appelle un modèle est la re-mesure du juge d'ambiguïté
(`experiments/ablation_l3_clean.py`, `runs/ablation_l3_clean_20260816.json`).

## Le F1 de 0,827 du juge d'ambiguïté

Le dépôt annonçait « le juge `gemini-2.5-flash` atteint F1 0,827 ± 0,058 », avec pour enseignement qualitatif
que seul le juge voyait le référent flou de *the latest iPad model*.

La rubrique transmise au juge (`_RUBRIC`, `benchmark_doctor/detectors/l3_ambiguity.py`) reprenait mot pour mot
des énoncés du corpus évalué : cinq dans le jeu annoté, sept dans le corpus complet. Quatre étaient des
positifs, `GitHub--5` (at least 500 stars), `Coursera--0` (renowned university), `Huggingface--23` (innovative
and widely recognized) et `Apple--11` (the latest iPad model) ; le cinquième, `GitHub--28`, était un négatif
dont le trait distinctif (most starred) figurait parmi les contre-exemples. Le 0,827 était le meilleur de
quatre exécutions du même juge à température 0, servies par le cache (0,804, 0,826, 0,815, 0,792), et le
`± 0,058` publié à côté était la dispersion entre plis de cette seule exécution.

J'ai réécrit la rubrique avec des exemples fabriqués, sur des domaines étrangers aux quinze sites de
WebVoyager, et rendu la règle exécutable par `experiments/check_rubric_leak.py`, qui échoue sur l'ancienne
rubrique et passe sur la nouvelle (5 suites de quatre mots reprises du corpus, 8 marqueurs de domaine et 7
mots d'exemple partagés, contre 0 partout). Puis j'ai refait la mesure, cinq exécutions par famille, moyenne
et écart-type inter-exécutions nommés comme tels.

| Approche | P | R | F1 | AUC | σ inter-plis | σ inter-exéc. | Coût / 139 |
|---|---:|---:|---:|---:|---:|---:|---:|
| référence, tout positif | 0,396 | 1,000 | 0,567 | 0,500 | 0,007 | | 0 $ |
| référence, majorité par site | 0,567 | 0,691 | 0,623 | 0,746 | 0,118 | | 0 $ |
| référence, règle lexicale à la main | 0,676 | 0,455 | 0,543 | 0,656 | 0,218 | | 0 $ |
| (a) TF-IDF 1-2 grammes, rég. log. | 0,660 | 0,600 | 0,629 | 0,776 | 0,124 | | 0 $ |
| (b) all-MiniLM-L6-v2, rég. log. | 0,543 | 0,691 | 0,608 | 0,732 | 0,120 | | 0 $ |
| (c) text-embedding-3-small, rég. log. | 0,621 | 0,655 | 0,637 | 0,787 | 0,121 | | 0,00007 $ |
| (d) juge flash, rubrique propre | 0,891 ± 0,001 | 0,596 ± 0,008 | 0,715 ± 0,006 | 0,772 ± 0,004 | 0,175 | 0,006 | 0,13524 $ |
| (d⁻) juge flash, rubrique fuitée du 15/08 | 0,831 ± 0,007 | 0,789 ± 0,021 | 0,810 ± 0,012 | 0,848 ± 0,013 | 0,078 | 0,012 | 0,14192 $ |
| (d⁰) juge flash, sans rubrique | 0,448 ± 0,012 | 0,764 ± 0,055 | 0,565 ± 0,024 | 0,627 ± 0,009 | 0,072 | 0,024 | 0,07468 $ |
| (e) juge flash-lite, rubrique propre | 0,627 ± 0,036 | 0,153 ± 0,021 | 0,245 ± 0,029 | 0,551 ± 0,010 | 0,129 | 0,029 | 0,03961 $ |
| (e⁻) juge flash-lite, rubrique fuitée | 0,686 ± 0,016 | 0,382 ± 0,026 | 0,490 ± 0,022 | 0,645 ± 0,005 | 0,234 | 0,022 | 0,03644 $ |

Les quatre premières exécutions du juge fuité sont celles du 15 août, et la reconstruction du prompt d'origine
touche le cache sur les 139 items, ce qui la valide. Les étendues des deux familles sont disjointes, et le
test exact de Mann-Whitney sur cinq exécutions contre cinq donne p = 0,0079. Retirer les cinq énoncés fuités
ne faisait perdre que 0,016 point de F1 ; refaire la mesure avec une rubrique propre en fait perdre 0,095, et
l'écart reste de 0,094 sur les 134 tâches hors items fuités, 0,703 ± 0,007 contre 0,797 ± 0,015. Les exemples
fuités enseignaient un motif transférable au-delà des cinq énoncés recopiés : restreint aux 55 positifs, le
McNemar donne 1 contre 12 en faveur du juge fuité (p = 0,0034), ce qui rend inopérante la correction par
retrait. Le détail par exécution est dans `runs/ablation_l3_clean_20260816.json`.

Le résultat change de nature sans tomber. L'AUC du juge propre vaut 0,772 contre 0,776 pour TF-IDF : sur
l'ordonnancement, les deux sont indiscernables. Ce qu'achète le juge est un point de fonctionnement : à rappel
identique de 0,600, il produit 4 faux positifs sur 84 négatifs quand TF-IDF en produit 17 (McNemar restreint
aux négatifs, p = 0,0044). Sur le F1 global, l'écart n'est pas significatif (p = 0,0596).

Quatre points restent ouverts. La fuite structurelle demeure et dépasse la fuite verbatim : le même juge privé
de la grille tombe à F1 0,565, la valeur de la stratégie « tout positif », et la grille transmise vaut donc
0,150 point de F1 contre 0,095 pour les énoncés recopiés ; le protocole mesure la reproductibilité d'une
grille d'étiquetage entre deux modèles, et retirer la grille reviendrait à mesurer autre chose. L'annotateur
est un modèle de langage unique, donc sans vérité terrain humaine pour la catégorie ambiguïté ni κ
inter-annotateurs mesurable. L'enseignement qualitatif du 15 août est réfuté, le rappel sur le critère A3
tombant de 70 % à 30 % avec une rubrique propre, le juge manquant alors `Apple--11`, l'exemple qui
l'illustrait. Enfin les 238 constats d'ambiguïté de `runs/health_20260815.json` ont été produits avec la
rubrique fuitée et n'ont pas été recalculés, faute de budget ; ils sont cités comme une borne haute, avec le
prompt utilisé.

## L'effondrement de `gemini-2.5-flash-lite` au niveau du hasard

Le dépôt écrivait que `gemini-2.5-flash-lite` s'effondrait au niveau du hasard, et publiait trois lignes à F1
0,567 avec tp 55, fp 84, fn 0, tn 0, c'est-à-dire « tout positif » sous un autre nom. Le seuil était calibré
par maximisation du F1. À 39,6 % de prévalence, « tout positif » vaut déjà F1 0,567, et le F1, qui n'a pas de
terme en vrais négatifs, sélectionne mécaniquement cette dégénérescence dès que le classifieur est faible.
L'AUC de `flash-lite` valait alors 0,649, au-dessus du hasard. J'ai calibré sur le J de Youden, nul par
construction pour « tout positif », et publié en regard le seuil fixe 0,5.

| Approche | seuil J | seuil fixe 0,5 | seuil max-F1 |
|---|---:|---:|---:|
| (a) TF-IDF | 0,629 | 0,627 | 0,636 |
| (c) embeddings | 0,637 | 0,618 | 0,632 |
| (d) juge flash, rubrique propre | 0,715 | 0,715 | 0,715 |
| (d⁰) juge flash, sans rubrique | 0,565 | 0,311 | 0,604 |
| (e) juge flash-lite, rubrique propre | 0,245 | 0,235 | 0,567 |
| (e⁻) juge flash-lite, rubrique fuitée | 0,490 | 0,482 | 0,562 |

Le classement ne change pas d'une colonne à l'autre, et pour le juge `flash` les trois sont identiques au
millième, son seuil de Youden valant 0,50 dans les 25 plis des cinq exécutions ; les précisions et rappels
complets à chaque seuil sont dans `runs/ablation_l3_clean_20260816.json`. La phrase du 15 août est redevenue
vraie pour une autre raison que celle qu'elle donnait : avec une rubrique propre, l'AUC de `flash-lite` tombe
à 0,551, et c'était la fuite qui maintenait le petit modèle au-dessus du hasard.

## La précision de 0,986 de la couche statique

La grille de validation publiait « L1 au seuil HIGH, précision 0,986 » contre la vérité « signalée par au
moins un des six annotateurs indépendants », et présentait ce chiffre comme une validation plus large que le
seul patch-set Magnitude. Sur les 72 vrais positifs, 71 sont des tâches Magnitude, le patch-set sur lequel les
détecteurs ont été réglés ; l'apport des cinq autres sources se réduit à une tâche, `Amazon--5`.

J'ai construit une validation hors échantillon (`experiments/validation_hors_echantillon.py`,
`runs/validation_hors_echantillon_20260816.json`). Le jeu de réglage réunit les 121 tâches patchées par
Magnitude, le jeu de validation les 522 restantes, l'intersection vide étant vérifiée par assertion à
l'exécution. La vérité de référence est « signalée par au moins un des cinq annotateurs autres que
Magnitude », 48 positifs, prévalence 0,0920. Chaque ligne porte la précision attendue au hasard, le lift, un
test binomial unilatéral et une p-valeur corrigée du groupement par site.

| Config | Seuil | Signalées | VP | P | Lift | R | p binom. | p corrigée site | Holm 5 % |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| L1 | HIGH | 2 | 1 | 0,500 | 5,44 | 0,021 | 0,175 | 0,174 | non |
| L1 | MEDIUM | 49 | 16 | 0,327 | 3,55 | 0,333 | 4,49·10⁻⁶ | 3,57·10⁻³ | oui |
| L2 | HIGH | 126 | 18 | 0,143 | 1,55 | 0,375 | 0,0404 | 0,0908 | non |
| L2 | MEDIUM | 126 | 18 | 0,143 | 1,55 | 0,375 | 0,0404 | 0,0908 | non |
| L3 | HIGH | 67 | 12 | 0,179 | 1,95 | 0,250 | 0,0183 | 0,0106 | non |
| L3 | MEDIUM | 238 | 26 | 0,109 | 1,19 | 0,542 | 0,206 | 0,0828 | non |
| L1+L2 | HIGH | 127 | 18 | 0,142 | 1,54 | 0,375 | 0,0431 | 1,000 | non |
| L1+L2 | MEDIUM | 164 | 28 | 0,171 | 1,86 | 0,583 | 1,05·10⁻³ | 0,0503 | non |
| L1+L3 | HIGH | 67 | 12 | 0,179 | 1,95 | 0,250 | 0,0183 | 0,0106 | non |
| L1+L3 | MEDIUM | 267 | 33 | 0,124 | 1,34 | 0,688 | 0,0506 | 0,0586 | non |
| L1+L2+L3 | HIGH | 177 | 26 | 0,147 | 1,60 | 0,542 | 0,0117 | 0,0183 | non |
| L1+L2+L3 | MEDIUM | 313 | 40 | 0,128 | 1,39 | 0,833 | 0,0217 | 0,0312 | non |

Douze configurations sont testées contre la même vérité. La procédure de Holm-Bonferroni descendante à 5 %,
valide sans hypothèse d'indépendance entre tests, ne laisse qu'une survivante, L1 au seuil MEDIUM (3,57·10⁻³
contre 0,05/12 = 4,17·10⁻³) ; la deuxième, L3 HIGH (0,0106), échoue contre 0,05/11 = 4,55·10⁻³. La correction
du groupement par site vient de ce que L2 mesure l'accès par hôte et propage un constat unique à toutes les
tâches du site : ses 126 tâches signalées sont quatre décisions (Allrecipes 40/40, Amazon 38/38, Booking
11/11, ESPN 37/37), et un test binomial sur n = 126 divise l'écart-type par 11 là où il faudrait le diviser
par 2. J'ai appliqué un test exact conditionnel stratifié par site à toutes les lignes, un test de permutation
exact au niveau site quand l'ensemble signalé est une réunion de sites entiers (les 1 365 façons de choisir 4
sites parmi 15, énumérées), et un intervalle de confiance obtenu en rééchantillonnant les 15 sites avec
remise. La significativité apparente de L2 ne survit pas, p passant de 0,0404 à 0,0908.

L1 au seuil MEDIUM est devenu le résultat de référence. Ses 49 constats sont répartis sur 9 sites sur 15, il
tient sur quatorze des quinze retraits de site (pire cas, sans GitHub : p = 0,106, lift 3,17), il tient quand
on retire Convergence de la vérité (p = 4,12·10⁻³), et son lift se retrouve entre 3,5 et 4,9 chez quatre
annotateurs sur cinq pris séparément, dont Fara (lift 4,51, p = 6,45·10⁻⁴) et Alumnium (lift 4,92). Le même
contrôle a fait apparaître un dénominateur faux dans la table des sept forks : `browseruse_tasks.jsonl`
contient encore les 55 identifiants que browser-use a lui-même déclarés impossibles, si bien que sur son
corpus réel de 588 tâches il naît à 3 constats (0,5 %) et non 12 (1,9 %), et arrive à 62 (10,5 %) au 15 août
2026. `analysis_longitudinal.py` retire désormais les exclusions déclarées de chaque fork avant de mesurer, et
le diff du rapport longitudinal est entièrement contenu dans la ligne browser-use.

Quatre choses restent ouvertes. La scission est disjointe sur les positifs et non sur les négatifs : le
réglage des détecteurs a consisté pour partie à supprimer des faux positifs, donc à regarder des tâches non
patchées, et le chiffre hors échantillon reste une borne haute. La vérité de validation est le jugement
d'autres praticiens, faillible et le plus souvent non motivé, et le silence d'une source compte comme
« conserver » même quand elle n'a jamais examiné la tâche, ce qui fait de la précision une borne basse et du
rappel une borne haute. Quinze clusters, c'est peu, et aucune correction ne crée de l'information qui n'existe
pas. Contre la vérité « un praticien a retiré la tâche », aucune configuration n'est significative à aucun
seuil, et ce résultat nul est publié tel quel.

## Les six annotateurs indépendants

Le dépôt fondait son appareil statistique sur six annotateurs distincts et qualifiés d'indépendants, dans le
README comme dans le champ `description` de `runs/validation_ablation_20260815.json`.

Convergence et Magnitude partagent 56 de leurs 60 réécritures communes au caractère près, soit 93,3 %. J'ai
d'abord lu ce fait comme une filiation, puis je suis allé aux sources primaires, et elles la démentent. Le
fichier `data/patches.json` de Magnitude enregistre pour chacune de ses 68 réécritures un champ `prev` qui
donne l'état de départ, et ce `prev` est égal à l'énoncé WebVoyager d'origine dans 68 cas sur 68, à l'énoncé
de Convergence dans 0 cas sur 60. Son script `data/patch_tasks.py` refuse d'appliquer un patch dont le `prev`
ne correspond pas au fichier d'entrée, lui-même bit à bit identique au corpus d'origine. Aucune mention de
Convergence, `proxy-lite`, `2025Valid` ou `WebVoyager2025` n'apparaît dans le dépôt Magnitude. Enfin Magnitude
n'hérite d'aucune des trois fautes propres à Convergence (`UNS A92024` devenu `UNS A92025`, le 29 février 2026
qui n'existe pas, le `today (February 17, 2026)` autocontradictoire) et corrige deux d'entre elles.

Le 93 % est la conséquence de deux chaînes de traitement mécaniques appliquant au même corpus la même règle
avec la même constante de deux ans. Cette constante est prédite par la date de l'artefact pour cinq
annotateurs sur six ; Convergence est le seul à surcorriger d'un an, et son README dit pourquoi, puisque son
décalage uniforme amène `Booking--8` exactement au 20 décembre 2025, la date de péremption qu'il annonce. Une
fois les millésimes neutralisés, la paire la plus identique du corpus n'est d'ailleurs plus celle-là : c'est
browser-use et Convergence, à 98,3 %, deux sources sans lien que sépare un seul entier.

| Configuration | Voix | κ Fleiss 3 cat. | κ Fleiss exclusion | signalée_1 | signalée_3 | par tous |
|---|---:|---:|---:|---:|---:|---:|
| A, six voix brutes | 6 | 0,7371 | 0,5136 | 169 | 123 | 68 |
| B, Convergence et Magnitude fusionnés | 5 | 0,7237 | 0,4682 | 169 | 119 | 73 |
| C, Convergence exclu | 5 | 0,7291 | 0,4718 | 166 | 118 | 73 |
| C′, Magnitude exclu | 5 | 0,7073 | 0,4350 | 167 | 113 | 68 |
| D, browser-use et Magnitude fusionnés | 5 | 0,7101 | 0,4292 | 169 | 115 | 70 |

Les cinq configurations tiennent dans une bande de trois points, κ de 0,707 à 0,737, toutes qualifiées de
substantielles au sens de Landis-Koch. La configuration A reste la valeur de référence, publiée avec sa bande
de sensibilité. Le mot « indépendants » doit disparaître du dépôt, pour une raison plus large que la paire
contestée : les six patch-sets observent le même corpus, y rencontrent le même défaut dominant, un millésime
figé dans l'énoncé concentré sur les 44 tâches Booking et les 42 Google Flights, et n'ont qu'un geste pour le
réparer. Ce retrait n'est pas fait, et un `grep -rniE "ind[ée]pendan"` sur le dépôt le montre. Le mot a quitté
les textes anglais rédigés à la main, `README.md` et `docs/METHODOLOGY.md`, ainsi que les légendes de figures,
mais il tient dans la chaîne qui régénère les artefacts : `run_all.py` l'écrit dans les descriptions de vérité
terrain que reçoit `runs/validation_ablation_20260815.json` et dans l'en-tête qu'il produit pour
`exports/README.md` ; `analysis_longitudinal.py` en fait un nom de champ, `annotateur_independant`, porté à
chaque jalon de `runs/longitudinal_20260815.json` et relu par `figures/make_figures.py` ; deux messages de
`benchmark_doctor/cli.py` qualifient encore les patch-sets d'indépendants. Corriger un texte sans corriger le
script qui l'écrit revient à le voir revenir à l'exécution suivante. Une occurrence relève d'un autre sens et
ne compte pas ici : la réserve d'Alumnium, dans `sources.py` et reprise dans `data/ground_truth.json`, dit que
son audit part du commit d'origine et n'est pas un re-audit de Magnitude, ce qui est une propriété de
filiation et non l'indépendance statistique que le mot revendiquait ailleurs. Deux réserves subsistent. L'historique de Magnitude est écrasé, cinq commits du même jour et
`patches.json` dans le commit initial, si bien que la démonstration repose sur la cohérence interne de
l'artefact et non sur l'observation de sa fabrication ; et je n'ai pas cherché de source tierce commune dont
les deux équipes seraient parties.

## Les 127 dégradations attribuées au canal d'accès

Le différentiel `diff_channel_artifact` était décrit comme « même corpus, un jour d'écart, seul le canal
change », et 127 tâches y étaient dégradées.

La carte navigateur cloud ne repose que sur 4 URL réellement mesurées, Allrecipes, Booking, ESPN et GitHub.
Les onze autres sites sont classés `unreachable`, signature dont le verdict de site est faux et dont le risque
est nul, donc notés A par défaut. Trente-neuf des 127 dégradations, soit 31 %, portent sur Amazon, un site
jamais mesuré au navigateur : c'est une absence de mesure convertie en note A. Les deux cartes diffèrent donc
par le canal et par la couverture, 4 sites mesurés au navigateur contre 15 en HTTP direct, et le garde-fou de
comparabilité, qui refuse l'interprétation, n'a besoin que d'une des deux raisons. Le chiffre 127 a été retiré
de tout argumentaire sur la dépendance au canal ; la valeur défendable est 4 URL divergentes sur 14, soit
28,6 % de la campagne L2. Reste ouvert que les quatre observations navigateur de
`runs/l2_browser_cloud_20260815.json` sont saisies à la main et non reproductibles depuis le code, et que le
paramètre κ du score publié dépend entièrement de trois d'entre elles ; la campagne du 16 août sur quinze
sites et quatre canaux (`experiments/RAPPORT_CANAUX.md`) borne cette faiblesse sans la lever.

## Les trois cartes de santé et la double échelle de notes

Trois cartes aux chiffres différents circulaient dans le dossier sans qu'aucune soit déclarée comme la
référence : stabilité moyenne 0,638 sans la couche solvabilité au 16 août, 0,585 avec solvabilité au 15 août,
0,856 pour la couche statique seule sur une autre échelle de notes.

Les deux premières reproduisent exactement, je les ai rejouées par `bdoctor score-model`. Le problème était de
rédaction : les tables de sensibilité publiées à côté du README étaient calculées sans la couche solvabilité
alors que le README publiait la carte avec, si bien que coller la stabilité de 0,585 et une sensibilité de 144
tâches en note D dans le même paragraphe aurait été faux, la valeur correspondante avec solvabilité étant 177.
S'y ajoutait une double échelle de notes, `models.TaskVerdict.grade` (0,85 / 0,60 / 0,35) contre
`scoring.grade_for` (0,75 / 0,50 / 0,25), qui donnait sur la même carte {A 239, B 155, C 180, D 69} contre
{A 219, B 142, C 170, D 112}. Le dépôt ne porte plus qu'une échelle, définie dans un seul fichier, et une
seule carte est citable, celle que produit `experiments/carte_canonique.py` par rejeu du journal gelé.

## Les 563 tâches du sous-ensemble exécutable

`exports/README.md` annonçait un sous-ensemble exécutable de 563 tâches, l'export conservant l'énoncé
d'origine dans le champ `question` et plaçant le correctif dans `patch_canonique`.

Sur ces 563 tâches, 84 portent un énoncé dont une date est révolue au 15 août 2026, réparties en 63 dans
`corriger`, 14 dans `noyau` et 7 dans `surveiller`, et 13 de ces énoncés ont un patch canonique lui-même
périmé, pour 14 patchs périmés dans tout le sous-ensemble, l'écart étant Google Flights--9, dont
l'énoncé est sain et le patch périmé. Les 14 tâches du `noyau` appartiennent au sous-ensemble décrit comme jamais signalé par personne et à
exécuter tel quel. Le chiffre publié est devenu « 563 tâches, dont 84 (14,9 %) portant une date révolue au 15
août 2026, soit 479 exécutables sans retouche ». Les tâches périmées sont marquées plutôt que retirées, pour
que le fichier reste une photographie à 643 lignes comparable dans le temps.

## Le backend d'ambiguïté appliqué aux 643 tâches

Le backend `tfidf` de la couche L3, celui qui sert par défaut, est entraîné sur la totalité des 139
annotations, puis l'audit lui fait scorer les 643 tâches, dont ces 139. In-sample, il signale 55 des 139
tâches annotées à 0,964 de précision ; hors plis, il tombe à 0,654 au seuil max-F1 dans la mesure du 15 août
et à 0,660 au seuil 0,5 sur le banc du 16, pour 50 signalements.

La carte produite avec le backend par défaut applique donc deux instruments au même corpus, un classifieur à
0,96 de précision sur 21,6 % des tâches et à 0,65 sur le reste. La valeur publiée est la précision hors plis ;
la valeur historique de 0,964 ne figure ici que pour être disqualifiée. Aucune carte produite avec ce backend
n'est citée comme mesure, et une carte `tfidf` qui serait publiée porterait dans ses limites la phrase disant
que 139 de ses 643 tâches ont servi à l'entraîner.

## La couverture de la suite de tests

Le nombre de tests qui passent était avancé comme signal de qualité. La mesure de couverture dit autre
chose : la suite couvre 20 % des instructions du paquet et des deux scripts de campagne. La couche statique
et le modèle de données sont éprouvés, `l1_reference` et `l1_sideeffect` à 100 %, `l1_temporal` à 92 %,
`models.py` à 95 %. En descendant, cela s'effondre : `cli.py` 31 %, `scoring.py` 32 %, c'est-à-dire que le
moteur de score n'est éprouvé qu'au tiers. Le reste n'est pas même importé par la suite : `report.py`,
`channels.py`, `l2_liveness.py`, `l2_campaign.py`, `l2_content.py`, les trois modules L3, les six modules
`ground_truth/` et `analysis_longitudinal.py`, tous à 0 %. Ne sont donc testés ni la dérivation de κ et de λ,
ni le garde-fou de comparabilité, ni la réconciliation des patch-sets, ni le classifieur anti-bot.

Ce qui échappe à la suite est précisément ce qui convertit des constats en notes publiées. Une régression y
déplacerait toutes les notes sans qu'aucun constat ne change, et le rejeu de la carte canonique la
détecterait plus sûrement qu'un test unitaire de plus.

Reproduire la mesure :

```
python3 -m coverage run --source=benchmark_doctor,run_all,analysis_longitudinal -m pytest tests/ -q
python3 -m coverage report
```

Un second défaut a été corrigé au passage : sur un clone frais, `data/raw/` étant absent, trois tests de
verrouillage se contentaient de se désactiver et la suite affichait 86 passés et 3 ignorés sans que rien ait
été vérifié. Ces trois tests échouent désormais au lieu d'être ignorés quand `BDOCTOR_REQUIRE_DATA=1`, et la
variable est posée dans la CI.

## Les chiffres L3 rejouables hors ligne

J'avais présenté le cache `runs/l3_cache/` comme ce qui rend les chiffres L3 reproductibles hors ligne et sans
dépense, et signalé qu'un `.gitignore` n'untracke pas des fichiers déjà committés.

Le contrôle dit l'inverse. `.gitignore` ignore `runs/l3_cache/`, et `git ls-tree -r HEAD --name-only` ne
renvoie aucun fichier de ce répertoire : le cache n'est pas versionné, et les 782 appels servis à coût nul
pendant mes contrôles l'ont été depuis un cache local, absent d'un clone frais. La conséquence est publiée
avec les chiffres L3 : un tiers qui clone le dépôt et rejoue la couche L3 rappelle l'API et obtient 2 à 4 % de
constats différents, le taux de bascule de verdict au seuil 0,5 valant 0,7 % pour la rubrique propre et 4,3 %
pour la rubrique fuitée. La décision de verser ou non le cache au dépôt n'est pas tranchée ; en l'état, la
reproduction hors ligne des chiffres L3 n'est pas offerte.

## Ce qui a tenu

Les trois κ de Fleiss ont été recalculés à la main depuis `data/ground_truth.json`, sans réutiliser
`stats.py` : Pobs 0,9192 et Pe 0,6928 donnent κ = 0,7371 pour les trois catégories, Pobs 0,9455 et Pe 0,8879
donnent κ = 0,5136 pour l'exclusion seule, et le κ par défaut vaut 0,7651. Les trois sont identiques aux
valeurs publiées. J'ai également re-téléchargé l'URL épinglée du corpus d'origine et recalculé son empreinte,
`sha256 69b19fd86c23f1a500244a3724e039aa7ca6a1223d03e11eb10e308d4f11c488` sur 643 lignes, égale à
`meta.corpus_sha256` : l'amorçage du corpus est vérifiable par un tiers.

J'ai re-sondé les quinze URL de départ le 16 août et comparé aux signatures du 15 : Allrecipes reste en
`paywall_402`, Amazon, Booking et ESPN restent en `antibot_challenge`, GitHub reste en `channel_blocked`, les
dix autres restent en `ok`, soit 0 signature changée sur 15. Cette mesure n'a pas laissé d'artefact dans
`runs/`, et c'est la seule qui sépare l'effet du proxy de l'effet des vingt-quatre heures dans les trois
signatures qui changent entre le 15 et le 16 août au tableau de `experiments/RAPPORT_CANAUX.md` : la journée
seule ne change rien, donc ce sont le proxy d'egress et la machine qui expliquent l'écart. La stabilité de la
couche L2, revendiquée sur trois minutes, tient à un jour.

Quatre contrôles sont restés sans reproche. La normalisation des identifiants entre les sept patch-sets ne
produit aucune collision ni aucun identifiant orphelin, malgré quatre conventions de séparateur et deux
renommages de sites. Les bornes de dates de `DateMention.is_past` et `is_future` sont correctes, sans
off-by-one ni problème de fuseau, et le détecteur refuse explicitement de trancher sur les dates sans
millésime. Les 65 réécritures datées du patch-set principal contiennent toutes une date révolue au 15 août
2026 et aucune ne conserve de date future, recomptées indépendamment avec `extract_date_mentions`. Enfin aucun
identifiant de tâche n'est codé en dur dans une décision de détecteur, les corrections apportées sur les faux
positifs étant linguistiques, ce qui borne la contamination résiduelle de la validation hors échantillon.

## Ce que je n'ai pas vérifié

Les quatre observations navigateur cloud sont saisies à la main et je n'ai pas pu les reproduire ; je n'ai
contrôlé que leur cohérence interne et leurs limites déclarées. La provenance des patch-sets autres que
WebVoyager n'a pas été établie par téléchargement, seul le corpus d'origine l'ayant été, vérifié par
empreinte, et les 109 raisons reconstituées de l'historique Alumnium n'ont pas été rejouées commit à commit.

La relecture manuelle des 121 raisons Magnitude (`magnitude_reason_labels.json`) est l'étiquetage d'un
annotateur unique, sans second codeur, donc sans accord inter-codeurs mesurable. Trois des six catégories
renseignées reposent sur moins de dix cas (T4 : 7, T5 : 5, T8 : 7), et T6 et T7 n'y apparaissent pas faute
d'une seule étiquette, alors que T7 est la deuxième catégorie du tableau des taux de signalement.

Le workflow `.github/workflows/weekly.yml` n'a jamais tourné sur GitHub et je ne l'ai pas simulé. Le contenu
réel des sites n'a fait l'objet d'aucune vérification manuelle : les 273 tâches que personne n'a jamais
signalées et que l'outil note sous A restent indécidées, ce que l'export dit déjà.
