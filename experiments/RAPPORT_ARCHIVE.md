# Vérification par archive : douze motifs de disparition confrontés à la Wayback Machine

Campagne du 18 août 2026. Douze tâches WebVoyager, échantillon fermé d'avance.
Script : `experiments/verif_archive.py`. Plan rejouable : `experiments/plan_archive.json`.
Données : `runs/archive_t2_20260818.json`. Journal des requêtes : `runs/archive_requetes.jsonl`.

La vérité terrain temporelle du mémoire est un registre fossile : des correctifs datés,
motivés en clair par des praticiens. Quand Magnitude écrit « GitHub Pro does not exist
anymore », je le crois sur parole. Aucune observation directe d'un état passé du web ne
l'appuyait jusqu'ici, ni par la Wayback Machine, ni par archive.is. Cette campagne teste, sur
douze cas, ce que devient ce témoignage quand on va regarder l'archive.

Ce qu'elle peut prouver et ce qu'elle ne peut pas tient en une distinction, et toute la
valeur du travail en dépend. La Wayback Machine archive des pages, pas des fonctionnalités.
Elle établit qu'une page existait à la date de passage du robot, avec quel statut et quel
contenu. Elle ne rejoue ni une recherche, ni un filtre, ni un parcours de réservation. Une
tâche formulée comme une quête (« trouve une recette végane à plus de 200 avis ») lui est
donc structurellement inaccessible, et c'est le cas de cinq des douze.

## 1. Le résultat en une phrase

**Sept confirmées, zéro infirmée, cinq non vérifiables, zéro insuffisante sur douze.**

Les sept cas à URL stable sont tous passés : l'archive montre l'objet présent dans la fenêtre
du gel du corpus, puis absent avant le gel du patch-set, et plus aucune présence ensuite. Les
cinq quêtes Allrecipes sont restées hors de portée, non par défaut de couverture mais par
nature.

Un huitième résultat n'entre dans aucune des quatre cases, et c'est le plus utile au mémoire.
Sur GitHub--29, l'objet visé était **déjà introuvable le jour où le benchmark a été gelé** :
la tâche n'a pas péri, elle est née invalide. Sur Apple--2, l'archive établit la même chose de
la fiche produit sans pouvoir aller jusqu'à la tâche. La section 5 distingue les deux, parce
que l'écart entre elles est précisément ce que cette méthode sait et ne sait pas faire.

## 2. Les douze verdicts

| Tâche | Motif du praticien | Verdict | Preuve principale |
|---|---|---|---|
| Apple--2 | « These phones are no longer sold and don't have prices listed anymore » | **CONFIRMÉE** | Page d'achat de l'iPhone 15 Pro le 2024-02-20 : « $999.00 » et « A17 Pro chip with 6-core GPU ». Page de gamme le 2025-06-27, cible de la redirection : plus aucune occurrence de « A17 Pro », ni en texte ni en HTML brut. |
| Apple--20 | « This phone is no longer sold » | **CONFIRMÉE** | Le 2024-03-01, la page d'achat porte le lien `/shop/buy-iphone/iphone-14/6.7-inch-display-256gb-purple-unlocked` et `<span class="current_price">$929.00</span>`. Encore chiffrée le 2025-02-01 ; le 2025-03-08, l'URL redirige vers le catalogue, où « iPhone 14 Plus » n'apparaît nulle part. |
| Apple--41 | « These are no longer sold with 64GB of storage, 128 GB is the minimum » | **CONFIRMÉE** | « 64 GB » présent le 2024-03-01, avec 34 occurrences de la forme collée en HTML brut, casse ignorée (8 « 64GB », 26 « 64gb » d'identifiants de configuration) ; zéro occurrence le 2024-12-03, le 2025-07-02 et le 2026-08-01, sur des pages plus fournies que celle de 2024. |
| GitHub--29 | « GitHub Pro does not exist anymore - only teams » | **CONFIRMÉE** | « GitHub Pro » présent le 2025-04-01 (bloc FAQ, 36 453 caractères visibles), absent le 2025-05-01 (25 174 caractères, zéro JSON-LD FAQPage), soit 66 jours avant le gel du patch-set. |
| Huggingface--10 | « argilla/notux-chat-ui no longer exists » | **CONFIRMÉE** | Espace servi le 2024-01-09 sous « Notux Chat - a Hugging Face Space by argilla » avec son bandeau « Running on » ; 401 et page 404 complète le 2024-12-17. |
| Huggingface--21 | « No longer exists in docs » | **CONFIRMÉE** | `pipeline("sentiment-analysis")` et le lien vers `distilbert-base-uncased-finetuned-sst-2-english` présents le 2024-01-21 et encore le 2025-02-26 ; page réécrite en « Quickstart » le 2025-03-30, sans l'un ni l'autre. |
| Huggingface--22 | « Does not exist in docs » | **CONFIRMÉE** | Guide servi en entier le 2024-01-21 et le 2024-05-04 ; le 2025-06-15, l'adresse ne sert plus qu'une coquille de 228 caractères : « The documentation page ADD_TENSORFLOW_MODEL doesn't exist in v4.52.3 ». |
| Allrecipes--3 | « DNE » | **NON VÉRIFIABLE** | La galerie éditoriale sur le sujet exact n'a aucun instantané ; sur la collection végane archivée, zéro `ratingValue` et zéro `aggregateRating`, la note n'existant qu'en glyphes SVG. |
| Allrecipes--16 | « DNE » | **NON VÉRIFIABLE** | « Prep Time » absent du texte visible des collections ; 60 liens de recette distincts archivés pour une collection annoncée à plus de 1 940 recettes. |
| Allrecipes--19 | « DNE » | **NON VÉRIFIABLE** | La seule lasagne de la collection porte « 193 Ratings », alors que l'énoncé demande des *reviews*, grandeur qu'Allrecipes distingue explicitement des notes. |
| Allrecipes--23 | « DNE » | **NON VÉRIFIABLE** | La seule page de recherche servie en 200 dans la fenêtre contient le conteneur `search-results` et un unique lien de recette, un encart promotionnel : la liste est injectée côté client. |
| Allrecipes--30 | « DNE » | **NON VÉRIFIABLE** | Aucune carte de collection ne porte d'ingrédients ; les compteurs d'avis dérivent d'un passage du robot à l'autre (25 puis 31 sur la même recette). |

Les deux moitiés du tableau n'ont pas le même statut. Pour les sept cas à URL stable, l'état
de chaque instantané est **dérivé** du test des chaînes déclarées dans le plan, et le verdict
de la règle : changer un verdict suppose de changer une observation. Les cinq NON VÉRIFIABLE
ne sont pas dérivés. Ce sont des qualifications de l'énoncé, posées par le plan : aucune URL
stable ne peut porter la réponse, donc il n'y a rien à mesurer. Les observations qui les
motivent, elles, sont rejouées par le script et figurent dans le JSON sous
`observations_d_appui`.

## 3. Ce que la campagne établit, et ce qu'elle ne permet pas d'établir

**Sept motifs sur douze passent du témoignage à l'observation directe et datée ; les cinq
autres, soit 42 % de l'échantillon, sont structurellement invérifiables par archive.** Les
deux chiffres se lisent ensemble. Le premier seul laisserait croire que la méthode se
généralise ; le second seul enterrerait un résultat solide. C'est ainsi que le chapitre 6 les
reprend : la campagne y borne une menace sur la validité de l'axe temporel sans la lever, et
le témoignage des praticiens reste seul pour le reste du corpus.

Le second constat me gêne davantage, et je préfère l'écrire : sur les sept cas vérifiables,
aucun n'a produit d'infirmation. Le mémoire soutient par ailleurs que les praticiens patchent
parfois par excès de prudence. Cette campagne ne l'alimente pas, et elle ne le contredit pas
non plus : l'échantillon a été choisi parmi les motifs de disparition explicites, ceux dont
l'objet est nommé et l'adresse stable, c'est-à-dire la population où la confirmation était la
plus probable. Un échantillon tiré des re-datations ou des reformulations d'énoncés donnerait
un tout autre taux ; je ne l'ai pas tiré.

Ce zéro ne vaut d'ailleurs que depuis une correction apportée en fin de campagne. Dans sa
première version, la règle ne pouvait pas produire d'infirmation : une sonde d'absence qui
échouait, c'est-à-dire un objet toujours là après le gel du patch-set, retombait en
« indéterminé » au lieu de dire « présent ». Le compteur à zéro ne mesurait rien. La règle
distingue désormais les témoins d'archivage des assertions qui portent l'absence, et rend
« présent » quand les premiers passent et que les secondes échouent. Le résultat est resté le
même une fois la correction faite, mais il est devenu falsifiable.

## 4. Les limites

Elles sont écrites contre le résultat, pas à côté.

**Douze cas d'un seul patch-set.** Tous viennent de Magnitude, gelé au 2025-07-06, et couvrent
quatre sites sur les quinze du benchmark. Rien ici ne se généralise aux 643 tâches, ni même
aux 121 patchs de ce patch-set.

**Sélection par motifs explicites.** Les sept cas à URL stable sont exactement ceux dont le
motif nomme un objet et une adresse. C'est un biais assumé, décrit en section 3 : il gonfle le
taux de confirmation.

**Couverture d'archive inégale, et la chance a joué.** Zéro verdict insuffisant ne veut pas
dire que la couverture est bonne en général : Huggingface--10 ne dispose que de trois
instantanés en tout, et Huggingface--22 présente un trou de treize mois entre mai 2024 et juin
2025, si bien que sa disparition n'est datable qu'à l'intérieur de cet intervalle. Deux
instantanés de la page d'achat Apple ne se rejouent pas du tout : l'archive y sert sa propre
page d'erreur. Un échantillon voisin aurait pu produire plusieurs insuffisants.

**Confirmer une disparition ne dit rien de l'exécutabilité.** C'est la limite la plus
importante. Établir que l'iPad mini 64 Go n'est plus vendu ne dit pas qu'un agent échouerait
sur la tâche, ni pourquoi : la page existe toujours, elle répond 200, et l'agent y parviendrait
sans encombre avant de buter sur une option manquante. La condition est nécessaire, jamais
suffisante.

**Ce qui est attesté est parfois plus étroit que le motif.** Trois cas méritent la précision.
Pour GitHub--29, l'archive montre la disparition du **nom de plan sur la page de tarifs**, pas
l'arrêt commercial du produit. Pour Huggingface--10, Hugging Face renvoie le même couple 401 /
404 pour un dépôt supprimé, rendu privé ou passé en accès restreint : l'espace n'était plus
accessible publiquement, ce qui ne veut pas dire qu'il a été effacé. Pour Huggingface--22, le
guide était encore servi sur le chemin `/main/en/` le 2025-03-21, trois mois avant le gel du
patch-set : ce qui a disparu, c'est l'adresse que la tâche visait, pas le texte. Cette
observation, qui joue contre le résultat, est citée dans le JSON au même rang que les autres.

**Le rendu archivé n'est pas la page.** Toutes les preuves portent sur le HTML archivé, jamais
sur un rendu visuel. Le prix affiché par Apple sur ses fiches marketing est injecté en
JavaScript et ne s'archive pas : pour Apple--2, l'archive atteste que la page d'achat affichait
« $999.00 » et que la fiche annonçait sa puce, pas que la fiche marketing montrait un prix.

**La chaîne de preuve change parfois d'adresse.** Sur Apple--2, la présence est observée sur la
page d'achat et sur la fiche marketing, l'absence sur la page de gamme vers laquelle la fiche
redirige depuis septembre 2024. C'est le protocole prévu pour les redirections, mais cela veut
dire que l'URL canonique du cas ne porte pas elle-même la disparition. Le JSON le signale
désormais : chaque instantané pris sur une autre adresse est marqué, et le champ
`instantanes_pris_sur_une_autre_url` les récapitule.

## 5. Une tâche née invalide, et une autre que l'archive ne tranche pas

**GitHub--29 était sans objet dès le gel du corpus.** L'énoncé demande de comparer le nombre
maximal de dépôts privés des plans Free et Pro. Or, le 2024-03-02, `github.com/pricing`
n'affichait ni carte ni colonne « Pro » : le nom n'y survivait que dans le bloc FAQ, et la
ligne « Private repositories » du tableau valait « Unlimited » pour les trois plans affichés,
Free, Team et Enterprise. La comparaison demandée était donc déjà impossible le jour du gel,
avant la disparition mesurée en avril-mai 2025. Le motif du praticien vise juste sur le fond
et date mal : ce qui a disparu au printemps 2025, c'est la dernière mention du nom, pas la
comparabilité, qui manquait dès l'origine.

**Apple--2 est le cas où la méthode montre sa limite.** L'énoncé demande de comparer les prix
et les puces de l'iPhone 14 Pro et de l'iPhone 15 Pro. Apple a cessé de servir la fiche
`apple.com/iphone-14-pro/` en septembre 2023 : le contrôle rejoué par le script compte, entre
le 2023-10-01 et le 2025-01-01, 155 enregistrements dont 125 revisites et 30 redirections, et
**aucun servi en 200**. L'instantané du 2024-02-28 de `apple.com/iphone/`, trois jours avant le
gel du corpus, confirme la mise à l'écart : sa navigation liste « iPhone 15 Pro / iPhone 15 /
iPhone 14 / iPhone 13 / iPhone SE / Compare », sans l'iPhone 14 Pro, dont le nom ne subsiste
que dans une note technique sur les tailles d'écran.

On aurait tort d'en conclure que la tâche était irréalisable. Le dernier élément de cette même
navigation, « Compare », mène à `apple.com/iphone/compare/`, dont l'instantané du 2024-02-29
contient encore quatre fois « iPhone 14 Pro », dont deux colonnes de comparaison : le modèle
restait comparable sur le site. Mais cette page n'expose ni prix ni puce dans son HTML archivé,
zéro occurrence de « A16 Bionic » comme de « $999 » : les deux grandeurs que l'énoncé demande y
sont injectées en JavaScript et ne s'archivent pas. L'archive établit donc que la fiche produit
avait disparu six mois avant le gel du corpus, et laisse ouverte la question de savoir si la
tâche restait exécutable par une autre route. C'est exactement la frontière annoncée en
section 4 : l'archive sait dire qu'une page a disparu, pas qu'une tâche a cessé d'être faisable.

Ces deux constats déplacent la thèse plutôt qu'ils ne la contredisent. Le mémoire soutient
qu'une tâche perd sa validité avec le temps ; GitHub--29 montre qu'une tâche peut être publiée
déjà périmée, et que la date de gel d'un corpus ne garantit pas la validité de son contenu à
cette date. Un dispositif qui daterait la péremption à partir du seul patch-set la placerait au
2025-07-06 alors qu'elle est acquise dès mars 2024 pour GitHub--29 et dès septembre 2023 pour
la fiche de l'iPhone 14 Pro : près de deux ans d'écart dans le second cas, et le gel du corpus
lui-même arrive six mois trop tard.

## 6. Protocole, coût et rejeu

La collecte a coûté **96 requêtes vers `web.archive.org`**, sous le plafond de 150 que le
script refuse de dépasser, le reste des lectures étant servi par le cache disque. S'y ajoutent
les relevés du statut du jour sur le web vivant (Apple, Hugging Face, Allrecipes, GitHub), qui
ne touchent pas l'archive et sont refaits à chaque exécution du script. Toutes les requêtes
émises figurent dans le champ `journal_requetes` du fichier de résultats, avec leur horodatage,
leur statut et l'étiquette de l'explorateur qui les a émises ; le journal brut vit dans
`runs/archive_requetes.jsonl`, que le `.gitignore` du dépôt exclut.

Le débit est sérialisé par un verrou inter-processus : une requête par seconde au plus, quel
que soit le nombre d'explorateurs travaillant en parallèle. L'en-tête User-Agent déclaré est
honnête et identifie le dépôt. Aucun recours à archive.is : pas d'API, protection anti-robot
agressive, et le contourner serait exactement ce que le mémoire refuse de faire.

Quatre défauts de l'outillage ont été trouvés en cours de campagne, tous par relecture croisée
et non par le programme qui produisait les mesures. Aucun n'a changé un verdict, et c'est
justement ce qui les rend instructifs : ils auraient pu.

Le premier était un faux négatif silencieux. Les assertions négatives portaient sur le texte
visible, d'où les balises sont retirées : une chaîne qui ne vit que dans un attribut `href` y
est invisible, et l'assertion ne pouvait donc jamais échouer. Elle avait produit une
affirmation fausse sur Huggingface--21, selon laquelle la page Quick tour n'aurait jamais nommé
son modèle par défaut, avec la conclusion attrayante d'un vice de conception d'origine.
L'archive dit le contraire : le modèle était nommé, comme cible du lien « pretrained model ».
L'affirmation a été supprimée et le type `ne_contient_pas_html` ajouté.

Le deuxième était un empoisonnement du cache : une réponse « 504 Gateway Time-out » de
l'archive avait été mise en cache comme s'il s'agissait d'une page archivée. Le garde-fou
ajouté pour l'empêcher ne cherchait sa signature que dans les 20 000 premiers octets, or la
page d'erreur de rejeu place son message après environ 149 ko de licences JavaScript
inlinées : il n'a donc jamais vu les deux pages d'erreur qui dormaient dans le cache. Le
contrôle porte désormais sur tout le corps, refuse aussi les corps vides et tout statut hors
2xx et 3xx, et les deux entrées empoisonnées ont été purgées.

Le troisième touchait la règle elle-même, décrit en section 3 : l'infirmation était
structurellement inatteignable.

Le quatrième était l'absence de contrôle de monotonie. Une seule absence observée dans une
fenêtre de dix-huit mois suffisait à conclure, même si l'objet réapparaissait ensuite : un 404
de maintenance aurait été lu comme une disparition. La règle exige maintenant qu'aucune
présence ne soit observée après la première absence retenue, faute de quoi le verdict tombe à
INSUFFISANT pour état non monotone. Les sept séquences réelles sont monotones et survivent à
cette règle plus stricte.

Une erreur d'analyse, enfin, mérite d'être signalée parce qu'elle est facile à commettre et
qu'elle a traversé presque toutes mes notes d'exploration : la colonne `length` de l'API CDX
donne la taille de l'enregistrement WARC compressé, pas celle de la page. Plusieurs arguments
de datation fondés sur des « chutes de taille » étaient faux, dont un où la page avait en
réalité grossi. Les tailles citées ici sont mesurées après décompression, et comptées en
caractères, ce que le script produit réellement.

Le rejeu est déterministe :

```bash
cd benchmark-doctor
.venv/bin/python experiments/verif_archive.py run
```

Le script relit `experiments/plan_archive.json`, refait les inventaires et les instantanés
(servis par le cache s'il est présent), réévalue chaque assertion et régénère
`runs/archive_t2_<AAAAMMJJ>.json`. Les verdicts du groupe à URL stable sont recalculés à chaque
exécution ; aucun n'est stocké.

## 7. Deux limites mesurées en marge, et une capture sur deux

Je voulais tirer de cette campagne, pour la soutenance seulement, une paire de captures
d'écran opposant l'état de deux pages d'accueil en 2024 et en 2026, à la condition que le
rendu archivé soit fidèle. Une seule des quatre remplit la condition, et l'échec des trois
autres est une mesure.

**Booking est absent de l'archive.** Une requête CDX sur `www.booking.com` de 1996 à 2026 ne
renvoie aucun instantané, sur aucune période. Le site n'est pas mal couvert, il n'est pas
couvert du tout. Puisque Booking est l'un des quinze sites du benchmark, cela veut dire que la
méthode de cette campagne ne peut, par construction, rien dire des tâches Booking, quelle que
soit la qualité de leurs motifs. La part invérifiable annoncée en section 3 est donc un
plancher, pas un plafond.

**Le rendu de l'archive vieillit.** L'instantané du 2024-03-01 de `apple.com` se rend
fidèlement, et il est conservé : `runs/captures_archive/apple_accueil_20240301.png`, page
entière, 1 280 sur 5 114 pixels, mise en page, visuels produits et pied de page complets. Il
montre la gamme iPhone mise en avant à la veille du gel du corpus, iPhone 15 Pro et iPhone 15,
sans trace d'un iPhone 14 Pro : c'est l'illustration de ce que la section 5 établit par le HTML.
Les instantanés de 2026, eux, ne se rendent pas. Sur celui du 2026-08-01, aucune des 50 images
de la page ne se charge ; sur celui du 2026-07-01, 24 sur 49. Ce n'est pas un défaut de
défilement différé, il a été déclenché avant la mesure. La paire opposant 2024 à 2026 n'est
donc pas produite, et seule la moitié qui remplit la condition est versée au dépôt.

Une précision sur la façon de juger cette fidélité, parce qu'elle a failli induire en erreur.
Le compte des images chargées, qui disqualifie les instantanés de 2026, vaut zéro sur zéro pour
celui de 2024 : la page d'accueil d'Apple de l'époque ne contient aucune balise `<img>`, ses
visuels étant des fonds CSS. Le même indicateur dit donc « rien ne charge » dans un cas où tout
s'affiche. C'est le rendu qui tranche ici, pas le compteur, et c'est une exception assumée à la
règle qui gouverne tout le reste de cette campagne.

Ces deux constats vont dans le même sens que le troisième piège du protocole, celui qui impose
de fonder les preuves sur le HTML archivé plutôt que sur un rendu : ce que la Wayback Machine
restitue le plus mal est précisément ce qu'un humain regarderait en premier.
