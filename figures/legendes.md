# Légendes des figures

Fichier écrit par `figures/make_figures.py` en même temps que les figures. Les chiffres
cités sont relus dans les fichiers de mesure de l'outil, jamais saisis à la main.
Date de mesure gelée : 15 août 2026.

Chaque figure est calibrée pour une largeur utile de 16 cm, les PNG
portent une résolution de 300 ppp et les PDF sont vectoriels avec leurs polices
incorporées, trois propriétés que `python3 figures/make_figures.py --check`
revérifie sur les fichiers écrits.

## Figure 1

Fichiers : `fig01_decadence_par_site.png` (300 ppp) et `fig01_decadence_par_site.pdf` (vectoriel)  
Source des données : `runs/health_20260815.json`  
Reproduction : `python3 figures/make_figures.py --only 1`

Figure 1. Décadence par site : les 643 tâches de WebVoyager notées au 15 août 2026. Chaque barre représente la totalité des tâches d'un site, ventilées par note de stabilité, les sites étant classés du plus dégradé au moins dégradé. La note agrège les constats des trois couches de détection selon la formule du chapitre 3. Sur l'ensemble du corpus, 433 tâches sur 643 (67,3 %) reçoivent une note inférieure à A, et le score moyen s'établit à 0,585. Deux sous-ensembles se détachent : Booking (score moyen 0,223, dont 33 tâches sur 44 notées D) et Google Flights (0,329), tous deux composés de tâches transactionnelles à date codée en dur. À l'opposé, Wolfram Alpha conserve un score moyen de 0,882. Sur 5 des 15 sites, aucune tâche n'atteint la note A : la part de tâches dégradées ne suffirait donc pas à ordonner les sites, c'est la gravité qui les sépare.

## Figure 2

Fichiers : `fig02_patches_magnitude_taxonomie.png` (300 ppp) et `fig02_patches_magnitude_taxonomie.pdf` (vectoriel)  
Source des données : `benchmark_doctor/ground_truth/magnitude_reason_labels.json`  
Reproduction : `python3 figures/make_figures.py --only 2`

Figure 2. Les 121 patches publiés par Magnitude le 6 juillet 2025, classés dans la taxonomie du chapitre 2 par relecture manuelle de chaque raison invoquée. À gauche, la catégorie principale, ventilée entre les 68 réécritures et les 53 suppressions ; à droite, les 22 catégories secondaires, qui comptent des co-occurrences et non des parts. La dérive temporelle domine avec 70 tâches, dont 68 traitées par simple réécriture de la date : c'est le mode de décadence le plus fréquent, et le seul que l'annotateur ait jugé réparable sans retirer la tâche du corpus. Viennent ensuite la dérive de contenu (21), l'accès et les effets de bord (11), l'instabilité d'interface (7), l'ambiguïté (5) et la dépendance de timing (7), toutes traitées par suppression. Les catégories T6 et T7 ne reçoivent aucune tâche en catégorie principale, ce qui ne signifie pas qu'elles sont absentes du corpus mais qu'aucune raison publiée ne les invoque comme cause première. 16 classements ont été notés comme cas frontaliers.

## Figure 3

Fichiers : `fig03_ablation_detecteurs.png` (300 ppp) et `fig03_ablation_detecteurs.pdf` (vectoriel)  
Source des données : `runs/validation_ablation_20260815.json`  
Reproduction : `python3 figures/make_figures.py --only 3`

Figure 3. Ablation des couches de détection, mesurée sur les constats seuls et jamais sur le score publié : celui-ci intègre un a priori tiré de la même vérité terrain, et le valider contre elle serait circulaire. La vérité de référence est « tâche signalée par au moins un des six annotateurs » (169 tâches sur 643). (a) Chaque configuration apparaît à ses deux seuils, reliés par un segment : le point plein est le seuil HIGH, le point creux le seuil MEDIUM. La couche L1 seule atteint une précision de 0,986 pour un rappel de 0,426 ; l'empilement complet L1+L2+L3 porte le rappel à 0,893 au seuil MEDIUM, mais la précision tombe à 0,356. L'outil complet est un instrument de tri, pas un instrument de verdict. En ordonnancement sans seuil, la meilleure aire sous la courbe revient à L1+L2 (AUC 0,831), contre 0,818 pour L1 seule et 0,775 pour l'empilement complet : ajouter la couche L3 améliore le rappel au seuil et dégrade l'ordonnancement. (b) Rappel par catégorie sur les 121 tâches étiquetées, au seuil MEDIUM ; la portion pleine de chaque barre correspond aux tâches signalées par un constat de la bonne catégorie, la portion hachurée à celles attrapées pour un autre motif. La dérive de contenu (T2) passe de 29 % avec L1 seule à 71 % avec les trois couches, mais seules 5 des 21 tâches le sont pour la bonne raison. Aucun détecteur ne couvre l'instabilité d'interface (T4) ni la dépendance de timing (T8) : quand ces tâches sont signalées, c'est toujours par un constat d'une autre catégorie.

## Figure 4

Fichiers : `fig04_courbe_longitudinale.png` (300 ppp) et `fig04_courbe_longitudinale.pdf` (vectoriel)  
Source des données : `runs/longitudinal_curves_20260815.csv et runs/longitudinal_20260815.json`  
Reproduction : `python3 figures/make_figures.py --only 4`

Figure 4. Mortalité des tâches de mars 2024 à août 2026, selon l'instrument de mesure. Les quatre séries sont des parts de leur propre corpus et partagent donc un axe unique, malgré des dénominateurs différents. La courbe A cumule les tâches signalées par au moins un des six annotateurs, aux dates de leurs publications respectives : elle passe de 18,8 % au premier audit de décembre 2024 à 26,3 % en mai 2026. Elle est massivement censurée à gauche, puisque personne n'a examiné le corpus pendant les neuf mois qui ont suivi sa publication : le trait pointillé initial est une reconstitution, pas une mesure. La courbe B applique un instrument constant, le détecteur temporel L1 rejoué mois par mois sur le corpus figé d'origine : elle est plate à 11,35 % depuis avril 2024, ce qui est un résultat en soi, le corpus d'origine ne contenant presque aucune date encore future à sa publication. La courbe B′ applique le même instrument au corpus réparé par Magnitude en juillet 2025 : partie de 0,34 % le jour de la réparation, elle atteint 10,51 % treize mois plus tard, ce qui montre qu'une réparation se défait. La courbe D sert de contrôle sur Online-Mind2Web, benchmark activement maintenu, dont le journal de remplacement donne 17,3 % de tâches remplacées sur la même période. L'estimateur retenu pour le mémoire est celui des incréments postérieurs au premier audit, soit 6,7 % par an [5,1 ; 8,8] ; l'instrument constant borne cette valeur par le bas à 1,9 % et le benchmark maintenu par le haut à 15,8 %.

## Figure 5

Fichiers : `fig05_cout_performance_l3.png` (300 ppp) et `fig05_cout_performance_l3.pdf` (vectoriel)  
Source des données : `runs/ablation_ambiguity_20260815.json`  
Reproduction : `python3 figures/make_figures.py --only 5`

Figure 5. Coût et performance des quatre approches candidates pour la couche L3, évaluées sur les 139 tâches du jeu d'annotation d'ambiguïté, étiquetées par un annotateur unique qui est un modèle de langage (`data/annotations_ambiguity.json`), sans vérité humaine, en validation croisée à cinq plis. L'ordonnée est le F1 au seuil de décision 0,5, l'abscisse le coût annuel d'une surveillance hebdomadaire des 643 tâches ; les méthodes sans appel facturé occupent le panneau de gauche, un axe logarithmique ne pouvant représenter la gratuité. Le plancher trivial, obtenu en déclarant toutes les tâches ambiguës, vaut F1 = 0,567 : une méthode qui ne le dépasse pas ne mesure rien. L'approche (a) TF-IDF avec régression logistique atteint 0,627 pour un coût nul, l'approche (c) par embeddings 0,618 pour 0,018 $ par an, et le juge LLM économique (d) 0,512 pour 1,75 $ par an. La seule configuration nettement supérieure est le même juge sur un modèle plus coûteux : 0,826 pour 6,82 $ par an, soit un ordre de grandeur de plus. Ce F1 est celui de la rubrique fuitée, dans laquelle 5 énoncés du jeu évalué avaient été recopiés, et c'est la plus haute des cinq valeurs obtenues avec cette rubrique, dont la moyenne vaut 0,810 ± 0,012. Le rejeu du 16 août 2026, rubrique nettoyée, ramène le même juge à 0,715 ± 0,006 (`runs/ablation_l3_clean_20260816.json`, détail dans `experiments/CONTRE_VERIFICATION.md`) ; le point tracé garde la valeur du 15 août 2026, le rejeu ne portant pas la projection de coût dont dépend l'abscisse. La qualité du juge tient au modèle bien plus qu'au prompt, puisque le même prompt sur un modèle économique perd 31 points de F1. Le coût reste, dans tous les cas de figure, négligeable devant celui d'une exécution d'agents sur le même corpus.

## Figure 6

Fichiers : `fig06_desaccord_inter_patcheurs.png` (300 ppp) et `fig06_desaccord_inter_patcheurs.pdf` (vectoriel)  
Source des données : `data/ground_truth.json`  
Reproduction : `python3 figures/make_figures.py --only 6`

Figure 6. Les six annotateurs ne mesurent pas le même benchmark. (a) Matrice orientée du désaccord dur : chaque case donne le nombre de tâches que l'annotateur en ligne a supprimées de son corpus et que l'annotateur en colonne a conservées sans la moindre modification. La matrice n'est pas symétrique, et elle ne doit pas l'être, les deux affirmations n'étant pas équivalentes. Le désaccord le plus marqué atteint 37 tâches et concerne browser-use 12/2024 contre Skyvern 05/2026 et Magnitude 07/2025 contre Skyvern 05/2026. Au total, 68 tâches font l'objet d'un désaccord dur, et 115 cas supplémentaires opposent une suppression à une réécriture. (b) Distribution du nombre d'annotateurs signalant chaque tâche, parmi les 169 tâches signalées au moins une fois. La distribution est bimodale : 68 tâches font l'unanimité des six annotateurs, 35 ne sont signalées que par un seul, et 474 tâches, non représentées ici, ne sont signalées par personne. Autrement dit, 40,2 % seulement des tâches signalées le sont à l'unanimité : le reste relève d'un arbitrage que chaque équipe a tranché seule, sans le publier.

## Figure 7

Fichiers : `fig07_architecture_fonctionnelle.png` (300 ppp) et `fig07_architecture_fonctionnelle.pdf` (vectoriel)  
Source des données : `schéma ; les chiffres cités proviennent de runs/health_20260815.json`  
Reproduction : `python3 figures/make_figures.py --only 7`

Figure 7. Architecture fonctionnelle de benchmark-doctor. Le schéma décrit ce que chaque étape produit et qui décide, non les modules du programme. Le corpus traverse trois couches de détection ordonnées par coût croissant : l'analyse statique L1, les sondes web L2 et le juge LLM L3. Chaque couche émet des constats horodatés portant une catégorie de la taxonomie, une sévérité, un canal d'observation et une confiance ; l'agrégation les combine par un OU-bruité en un score de stabilité et une note de A à D, restitués dans une carte de santé. La campagne complète sur les 643 tâches a coûté 0,263 $ pour 1 331 appels, soit 0,00041 $ par tâche, la totalité étant imputable à la couche L3. Le point important est la boucle : la carte de santé produit un tri, l'arbitrage reste humain, et le sous-ensemble vérifié qui en résulte retourne dans la file de surveillance. Une réparation est une observation datée de plus, ce que confirme la courbe B′ de la figure 4.

## Figures sans générateur

Quatre images du dossier `figures/` ne sortent pas de ce script : un schéma et trois
montages de captures d'écran, conservés tels quels. Le contrôle `--check` ne les couvre
pas.

`fig11_pile_agent_juge.png`, citée par le mémoire en figure 1 (section 1.2)  
Ce qu'elle montre : la boucle d'un agent web, de l'écran du site à l'action en passant par
l'encodeur visuel et le transformer, avec le juge automatique qui lit l'écran par le même
encodeur que l'agent qu'il note.  
Origine de l'image : rendu de `figures/fig11_pile_agent_juge.svg`, versionné dans le même
dossier.

`fig08_espn_deux_origines.png`, citée par le mémoire en figure 2 (section 2.1)  
Ce qu'elle montre : espn.com interrogé le 16 août 2026 par un navigateur réel, servi depuis
une adresse résidentielle et refusé en 403 depuis un centre de données.  
Origine de l'image : montage de `runs/captures/browser_residential_espn_p1.jpg` et de
`runs/captures/browser_datacenter_espn_p1.jpg`, campagne de la matrice des canaux.

`fig09_allrecipes_mur_antibot.png`, non citée par le mémoire  
Ce qu'elle montre : allrecipes.com le même jour, servi depuis l'adresse résidentielle et
arrêté par un mur anti-robot Cloudflare depuis le centre de données, au second passage
seulement.  
Origine de l'image : montage de `runs/captures/browser_residential_allrecipes_p1.jpg` et de
`runs/captures/browser_datacenter_allrecipes_p2.jpg`.

`soutenance_apple_2024_2026.png`, non citée par le mémoire  
Ce qu'elle montre : la page d'accueil d'Apple à la veille du gel du corpus, Vision Pro et
iPhone 15 Pro, puis la même page deux ans et demi plus tard, MacBook Air M5 et gamme
d'août 2026.  
Origine de l'image : montage de `runs/captures_archive/apple_accueil_20240301.png`, relevé
dans l'Internet Archive, et de `runs/captures/browser_residential_apple_p1.jpg`.
