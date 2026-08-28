# Matrice des canaux : ce qui débloque un site, le moteur de rendu ou l'adresse IP

Campagne du 16 août 2026. 15 sites, 4 canaux, 2 passes espacées d'une heure.
Script : `experiments/campagne_matrice.sh`. Données : `runs/matrice/` et
`runs/l2_matrice_canaux_20260816.json`. Preuves : `runs/har/` et `runs/captures/`.

Ce rapport documente et borne la faiblesse principale du dossier. Il ne la lève pas, et la
section 8 dit pourquoi. La dépendance au canal d'accès reposait jusqu'ici sur quatre
observations de navigateur saisies à la main, non reproductibles depuis le code, et le
paramètre κ = 0,40 du score publié était calibré sur trois d'entre elles. Le plan
d'expérience confondait par ailleurs deux facteurs : le canal « HTTP direct » et le canal
« navigateur cloud » différaient à la fois par le moteur de rendu et par l'origine réseau,
si bien qu'aucun écart ne pouvait être attribué à l'un plutôt qu'à l'autre.

J'ai donc mesuré les quatre cases du plan croisé, dans la même fenêtre de temps et avec le
même classifieur.

| | moteur : aucun (client HTTP) | moteur : navigateur réel |
|---|---|---|
| **origine : datacenter** | `http_datacenter` | `browser_datacenter` |
| **origine : résidentielle** | `http_residential` | `browser_residential` |

Les cellules résidentielles sont sorties par un abonnement grand public mobile
(AS51207 Free Mobile SAS, France), les cellules datacenter par un serveur loué
(AS16276 OVH SAS, France). Les deux origines sont en France, mais cela n'écarte pas le
géo-routage : les en-têtes de point de présence conservés dans les observations montrent
que les deux origines n'atteignent jamais le même point d'entrée des réseaux de diffusion
(Francfort, Amsterdam et Zurich côté serveur, Paris côté résidentiel), et que les éditions
servies diffèrent, Booking en anglais américain d'un côté et en français de l'autre, ESPN
redirigé vers son édition britannique depuis l'adresse résidentielle. Le contraste
d'origine embarque donc trois choses à la fois : la réputation de l'adresse, le chemin de
diffusion, et l'édition localisée du site. Le facteur mesuré est cet ensemble, pas la
réputation seule.

## 1. Le résultat en une phrase

Les deux facteurs existent et portent sur des sites différents, mais leur poids relatif
n'est pas mesurable à cet effectif : quatre à cinq sites basculent sous l'effet du moteur,
deux sous l'effet de l'origine, et l'écart n'est pas distinguable du hasard.

Ce que la campagne établit solidement est plus utile qu'un classement des deux facteurs.
Sur Booking et Amazon, changer d'adresse IP ne sert à rien et seul le navigateur ouvre la
porte. Sur ESPN, aucun des deux ne suffit seul. Sur Allrecipes, la réponse dépend de la
passe : à la première, seule l'adresse comptait ; une heure plus tard, l'adresse
résidentielle était bloquée elle aussi et seul le navigateur passait encore. Un dispositif
de mesure qui ne fait varier qu'un seul de ces deux paramètres se croira donc représentatif
alors qu'il sera aveugle à une partie du corpus, et la thèse du mémoire s'en trouve
confirmée dans son principe : la validité d'une tâche n'est pas une propriété de la tâche.

Le basculement d'Allrecipes entre les deux passes est le résultat que je n'attendais pas,
et c'est celui qui justifie à lui seul l'exigence de répétabilité. Avec une seule passe,
j'aurais publié que l'origine réseau explique entièrement le comportement de ce site. La
seconde passe le contredit une heure plus tard.

## 2. Les 15 sites vus par les 4 canaux

| Site | HTTP · datacenter | HTTP · résidentiel | Navigateur · résidentiel | Navigateur · datacenter |
|---|---|---|---|---|
| Allrecipes | `forbidden_403` | `ok` → `forbidden_403` | `ok` | `antibot_challenge` → `forbidden_403` |
| Amazon | `antibot_challenge` | `antibot_challenge` | `ok` | `ok` |
| Apple | `ok` | `ok` | `ok` | `ok` |
| ArXiv | `ok` | `ok` | `ok` | `ok` |
| BBC News | `ok` | `ok` | `ok` | `ok` |
| Booking | `antibot_challenge` | `antibot_challenge` | `ok` | `ok` |
| Cambridge Dictionary | `ok` | `ok` | `ok` | `ok` |
| Coursera | `ok` | `ok` | `ok` | `ok` |
| ESPN | `forbidden_403` | `antibot_challenge` | `ok` | `forbidden_403` |
| GitHub | `ok` | `ok` | `ok` | `ok` |
| Google Flights | `ok` | `ok` | `ok` | `ok` |
| Google Map | `ok` | `ok` | `ok` | `ok` |
| Google Search | `ok` | `ok` | `ok` | `ok` |
| Huggingface | `ok` | `ok` | `ok` | `ok` |
| Wolfram Alpha | `ok` | `ok` | `captcha` | `captcha` |

## 3. Les deux facteurs isolés

Chaque contraste ne fait varier qu'un facteur, l'autre étant tenu constant. C'est ce que
la campagne du 15 août ne pouvait pas faire, faute de disposer des quatre cases.

| Contraste | Passe | Sites changeant de verdict | Lesquels |
|---|---|---|---|
| Changer de **moteur**, origine datacenter tenue fixe | 1 | **3** / 15 | Amazon, Booking, Wolfram Alpha |
| Changer de **moteur**, origine datacenter tenue fixe | 2 | **3** / 15 | Amazon, Booking, Wolfram Alpha |
| Changer de **moteur**, origine résidentielle tenue fixe | 1 | **4** / 15 | Amazon, Booking, ESPN, Wolfram Alpha |
| Changer de **moteur**, origine résidentielle tenue fixe | 2 | **5** / 15 | Allrecipes, Amazon, Booking, ESPN, Wolfram Alpha |
| Changer d'**origine**, moteur HTTP tenu fixe | 1 | **1** / 15 | Allrecipes |
| Changer d'**origine**, moteur HTTP tenu fixe | 2 | **0** / 15 | aucun |
| Changer d'**origine**, moteur navigateur tenu fixe | 1 | **2** / 15 | Allrecipes, ESPN |
| Changer d'**origine**, moteur navigateur tenu fixe | 2 | **2** / 15 | Allrecipes, ESPN |

Ce tableau compte des bascules, pas des sites, et un site peut basculer sous les deux
facteurs. En raisonnant sur les ensembles de sites plutôt que sur les compteurs :

| Passe | Sites sensibles au moteur | Sites sensibles à l'origine | Sensibles aux deux | Fisher exact, p bilatéral |
|---|---|---|---|---|
| 1 | **4** / 15 : Amazon, Booking, ESPN, Wolfram Alpha | **2** / 15 : Allrecipes, ESPN | ESPN | **0.6513** |
| 2 | **5** / 15 : Allrecipes, Amazon, Booking, ESPN, Wolfram Alpha | **2** / 15 : Allrecipes, ESPN | Allrecipes, ESPN | **0.3898** |

Le test exact de Fisher donne une valeur de p très élevée dans les deux passes. À quinze
sites, l'écart entre ces effectifs ne se distingue pas d'une fluctuation d'échantillonnage.
Je ne peux donc pas écrire que le moteur pèse deux fois plus lourd que l'origine, et la
première version de ce rapport le faisait à tort.

Ce qui reste, et qui est solide, est la dissociation. Les sites que fait basculer le moteur
ne sont pas tous ceux que fait basculer l'origine. Amazon et Booking répondent au moteur et
sont indifférents à l'adresse, dans les deux passes. À l'inverse, aucun site n'est
durablement sensible à la seule adresse : Allrecipes l'était à la première passe et ne l'est
plus à la seconde. Un facteur dominant en moyenne, à supposer qu'on parvienne à l'établir,
ne serait de toute façon pas un facteur suffisant.

## 4. Accord entre canaux, et réestimation de κ

Deux grandeurs portent la lettre κ dans ce dossier, et les confondre serait une faute. Le
κ de Cohen mesure l'accord entre deux canaux qui jugent les mêmes sites, corrigé du
hasard ; il est symétrique. Le κ du score publié mesure autre chose : sachant que le canal
HTTP depuis un centre de données annonce un refus, quelle chance ce refus a-t-il d'être
réel. Il est asymétrique, et le mémoire l'estime par la règle de succession de Laplace,
(k+1)/(n+2), sur n = 3 URL dont k = 1 blocage confirmé, ce qui donne 0,40.

### 4.1 κ de Cohen

| Paire de canaux | Passe | n | Accord observé | κ de Cohen | Désaccords | p (permutation) |
|---|---|---|---|---|---|---|
| HTTP · datacenter ↔ HTTP · résidentiel | 1 | 15 | 0.9333 | **0.815** | 1 | 0.0091 |
| HTTP · datacenter ↔ Navigateur · résidentiel | 1 | 15 | 0.6667 | **-0.119** | 5 | 1.0 |
| HTTP · datacenter ↔ Navigateur · datacenter | 1 | 15 | 0.8 | **0.444** | 3 | 0.153 |
| HTTP · résidentiel ↔ Navigateur · résidentiel | 1 | 15 | 0.7333 | **-0.111** | 4 | 1.0 |
| HTTP · résidentiel ↔ Navigateur · datacenter | 1 | 15 | 0.7333 | **0.167** | 4 | 1.0 |
| Navigateur · résidentiel ↔ Navigateur · datacenter | 1 | 15 | 0.8667 | **0.444** | 2 | 0.1999 |
| HTTP · datacenter ↔ HTTP · résidentiel | 2 | 15 | 1.0 | **1.000** | 0 | 0.0006 |
| HTTP · datacenter ↔ Navigateur · résidentiel | 2 | 15 | 0.6667 | **-0.119** | 5 | 1.0 |
| HTTP · datacenter ↔ Navigateur · datacenter | 2 | 15 | 0.8 | **0.444** | 3 | 0.153 |
| HTTP · résidentiel ↔ Navigateur · résidentiel | 2 | 15 | 0.6667 | **-0.119** | 5 | 1.0 |
| HTTP · résidentiel ↔ Navigateur · datacenter | 2 | 15 | 0.8 | **0.444** | 3 | 0.153 |
| Navigateur · résidentiel ↔ Navigateur · datacenter | 2 | 15 | 0.8667 | **0.444** | 2 | 0.1999 |

Ces valeurs demandent trois précautions de lecture, dont la dernière annule presque la
première.

D'abord, le plus fort accord est celui des deux canaux HTTP. Changer d'adresse sans
changer de moteur laisse la plupart des verdicts en place. Il faut noter aussitôt que
c'est aussi la paire qui partage le plus de méthode, puisque les deux cellules utilisent
le même client, les mêmes en-têtes et le même chemin de code : une part de cet accord
mesure l'instrument plutôt que les sites.

Ensuite, deux paires obtiennent un κ négatif. La tentation est d'y lire un désaccord
systématique. Ce serait une erreur : avec onze à quatorze verdicts `ok` sur quinze, les
marges sont si déséquilibrées que κ devient piloté par la prévalence et non par l'accord.
Le test de permutation leur donne p = 1, c'est-à-dire qu'un remélange au hasard des
verdicts fait aussi bien dans la totalité des tirages.

Enfin, et c'est ce qui doit être retenu, une seule paire sur six atteint un seuil de
signification, celle des deux canaux HTTP. Toutes les paires impliquant un navigateur ont
p supérieur à 0,15. Le tableau est donc surtout utile pour ce qu'il interdit d'affirmer.
Je le publie parce que le protocole le demandait, et parce qu'un κ de Cohen sur quinze
sites est précisément le genre de chiffre qu'un lecteur pressé surinterpréterait s'il le
trouvait sans cet avertissement.

### 4.2 Réestimation du κ du score publié

| Canal juge | Passe | n refus annoncés | k confirmés | κ = (k+1)/(n+2) | Proportion brute | IC 95 % sur la proportion |
|---|---|---|---|---|---|---|
| HTTP · résidentiel | 1 | 4 | 3 | **0.6667** | 0.75 | [0.284 ; 0.972] |
| Navigateur · résidentiel | 1 | 4 | 0 | **0.1667** | 0.0 | [0.000 ; 0.445] |
| Navigateur · datacenter | 1 | 4 | 2 | **0.5** | 0.5 | [0.123 ; 0.877] |
| HTTP · résidentiel | 2 | 4 | 4 | **0.8333** | 1.0 | [0.555 ; 1.000] |
| Navigateur · résidentiel | 2 | 4 | 0 | **0.1667** | 0.0 | [0.000 ; 0.445] |
| Navigateur · datacenter | 2 | 4 | 2 | **0.5** | 0.5 | [0.123 ; 0.877] |

Le mémoire traite κ comme une propriété du canal accusé : il écrit que le canal
`http_datacenter` porte κ = 0,40, comme on énoncerait la précision d'un instrument. Cette
lecture ne tient pas. κ n'est pas une propriété d'un canal mais d'un couple de canaux.
Selon le canal pris pour juge, la même cellule `http_datacenter` obtient une crédibilité
qui va de 0,17 à 0,83.

Trois remarques, dont deux vont contre l'intérêt du résultat.

La valeur comparable à celle du mémoire est celle qui prend pour juge un navigateur en
centre de données, puisque c'est ce qu'était Browserbase. Sur cette base, κ ne s'effondre
pas : il monte légèrement, ce qu'il faut dire dans le sens qui dessert la thèse, puisque
le mémoire rappelle lui-même qu'un κ plus élevé produit davantage de tâches mortes.

Mais cette stabilité de la valeur masque un renversement complet de son contenu. La seule
confirmation sur laquelle reposait le 0,40 était Booking ; la campagne l'infirme, puisque
le navigateur y voit la page. Les deux confirmations nouvelles sont Allrecipes et ESPN,
c'est-à-dire précisément les deux réfutations du mémoire. Le nombre est presque le même,
les sites qui le produisent sont les inverses.

Enfin, les intervalles de crédibilité à 95 % de ces proportions se recouvrent tous, et ils
recouvrent aussi celui du mémoire. Sur quatre refus, une confirmation de plus ou de moins
déplace κ de 0,17. Aucune de ces valeurs n'exclut aucune autre, et je ne propose donc pas
de remplacer 0,40 par l'une d'elles. Je propose de cesser d'écrire κ sans nommer le canal
qui juge.

## 5. Les sites qui divergent, nommément

| Site | Verdicts distincts | Facteur qui explique le mieux |
|---|---|---|
| Allrecipes | HTTP · datacenter → `forbidden_403`, HTTP · résidentiel → `ok`, Navigateur · résidentiel → `ok`, Navigateur · datacenter → `antibot_challenge` | **origine réseau** |
| Amazon | HTTP · datacenter → `antibot_challenge`, HTTP · résidentiel → `antibot_challenge`, Navigateur · résidentiel → `ok`, Navigateur · datacenter → `ok` | **moteur de rendu** |
| Booking | HTTP · datacenter → `antibot_challenge`, HTTP · résidentiel → `antibot_challenge`, Navigateur · résidentiel → `ok`, Navigateur · datacenter → `ok` | **moteur de rendu** |
| ESPN | HTTP · datacenter → `forbidden_403`, HTTP · résidentiel → `antibot_challenge`, Navigateur · résidentiel → `ok`, Navigateur · datacenter → `forbidden_403` | **interaction** : ni l'un ni l'autre seul ne suffit |
| Wolfram Alpha | HTTP · datacenter → `ok`, HTTP · résidentiel → `ok`, Navigateur · résidentiel → `captcha`, Navigateur · datacenter → `captcha` | **moteur de rendu** |

Pour chacun, l'hypothèse la plus simple compatible avec les quatre cellules et avec les
pièces conservées. Ce sont des hypothèses : la campagne mesure des verdicts, elle
n'inspecte pas les règles des dispositifs de filtrage.

**Allrecipes, le seul site instable de la campagne.** À la première passe, il répond 200 et
sert sa page d'accueil à l'adresse résidentielle, avec ou sans navigateur, et refuse depuis
le serveur loué dans les deux cas ; la capture
`runs/captures/browser_residential_allrecipes_p1.jpg` montre la page de recettes réelle et
`runs/captures/browser_datacenter_allrecipes_p1.jpg` le mur *Verify you are human* de
Cloudflare. L'origine expliquait alors tout. Une heure plus tard, le client HTTP
résidentiel reçoit un 403 à son tour, et seul le navigateur résidentiel passe encore.

Trois explications restent ouvertes et la campagne ne les départage pas. La première est que
le site a resserré sa politique dans l'intervalle. La deuxième est que mes propres requêtes
l'ont déclenchée : j'ai sollicité cet hôte quatre fois en une heure depuis la même adresse,
ce qui est peu, mais pas rien pour un éditeur qui facture l'accès automatisé. La troisième
est que l'adresse mobile a changé entre les deux passes, ce que je n'ai pas instrumenté.

Deux réserves valent aussi pour la première passe. Le 402 *pay-per-crawl* qui a rendu ce site
célèbre dans ce dossier appartient à la mesure du 15 août, pas à celle-ci : le 16, la réponse
est un défi ordinaire. Et les deux origines n'atteignent pas le même point de présence
Cloudflare, si bien qu'une politique configurée par région reste une explication concurrente
de la réputation d'adresse.

**Amazon et Booking.** Les deux opposent au client HTTP un défi servi en 202 par AWS WAF,
avec l'en-tête `x-amzn-waf-action: challenge`, dans les deux origines. Les deux répondent
normalement au navigateur, dans les deux origines. Pour Booking, le HAR montre bien la
séquence attendue, un 202 puis la page : le navigateur a exécuté le défi. Pour Amazon, le
corps réseau reçu par le navigateur est directement la vraie page et aucun 202 n'apparaît,
si bien qu'une explication concurrente tient : le site n'a peut-être pas opposé de défi au
navigateur, plutôt que le navigateur ne l'ait résolu. Le résultat, lui, est le même. Sur
ces deux sites, changer d'adresse ne sert à rien.

**ESPN.** Aucun facteur seul ne suffit : le site n'est accessible que par la combinaison
du navigateur et de l'adresse résidentielle. L'hypothèse d'un score de risque cumulant
plusieurs signaux est possible, mais elle n'est pas la plus simple. Le corps du 403 reçu
depuis le serveur est une page d'erreur générique CloudFront, sans en-tête de pare-feu
applicatif, ce qui ressemble davantage à un blocage de préfixe au bord du réseau de
diffusion. Et l'adresse résidentielle est routée vers l'édition britannique du site,
`espn.co.uk`, quand le serveur interroge `espn.com`. Deux portes indépendantes, ou deux
éditions différentes du même site, expliquent la matrice aussi bien qu'un score unique.

**Wolfram Alpha, qui n'est pas un site divergent mais un défaut du classifieur.** Le
verdict `captcha` rendu sur les deux cellules navigateur est un faux positif. Le marqueur
qui le déclenche est la chaîne `"captchaApi":"/n/v1/api/captcha"`, une adresse d'interface
de programmation dans un objet de configuration JavaScript. Le titre de la page est
`Wolfram|Alpha: Computational Intelligence` et la capture
`runs/captures/browser_residential_wolfram_alpha_p1.jpg` montre la page d'accueil complète,
sans aucun test de vérification. La même chaîne est présente dans le corps servi au client
HTTP, mais au-delà des 4 000 caractères de l'extrait classifié, si bien que le canal HTTP
ne la voit pas. La différence de verdict entre les canaux ne vient donc pas des sites : elle
vient de ce que le DOM rendu est plus compact que le corps servi, et amène la chaîne à
l'intérieur de la fenêtre de classification.

Ce cas a coûté à la première version de ce rapport sa conclusion la plus frappante. J'y
écrivais que le canal agit dans les deux sens et qu'un navigateur peut aggraver le sort
d'un agent. Aucun site de la campagne ne le montre. La section 6 mesure l'effet de ce faux
positif sur tous les chiffres.

Les dix autres sites rendent le même verdict dans les quatre cellules. Il faut le dire
aussi nettement que les divergences : sur les deux tiers du corpus, le canal n'a aucune
importance.

### 5.1 Confrontation aux quatre observations du 15 août

| URL mesurée le 15/08 | Browserbase (15/08) | Navigateur · datacenter (campagne) | Comparable ? |
|---|---|---|---|
| `https://www.allrecipes.com/` | `ok` | `antibot_challenge` | **oui**, divergent |
| `https://www.booking.com/` | `antibot_challenge` | `ok` | **oui**, divergent |
| `https://www.espn.com/` | `ok` | `forbidden_403` | **oui**, divergent |
| `https://github.com/openai/openai-python` | `(non publiée)` | n/a | **non** : URL absente du corpus de la campagne, qui mesure la racine `https://github.com/` |

Deux des trois observations comparables divergent de ma cellule navigateur en centre de
données. Sur Allrecipes et ESPN, Browserbase voyait la page là où mon serveur voit un
refus. Sur Booking, la divergence n'est qu'apparente : les deux navigateurs ont rendu la
page réelle, et seule l'étiquette diffère, parce que la signature publiée pour Browserbase
vient de la règle du code 202 que l'annexe A décrit comme un défaut du classifieur. Il
serait malhonnête d'invoquer ce défaut pour excuser mes propres cellules et de m'en servir
comme preuve contre Browserbase.

Je ne peux pas trancher entre les explications des deux divergences réelles, et je
m'interdis de choisir la plus flatteuse. Quatre au moins sont compatibles avec les
données : le fournisseur ne sort pas par les mêmes adresses que mon serveur, Browserbase
applique par défaut des mesures d'évitement de détection que je n'utilise pas, la mesure du
15 août portait sur des adresses américaines quand la mienne est européenne, et les deux
campagnes sont séparées d'une journée.

Ce que ces divergences suggèrent en revanche, c'est que « navigateur cloud » désigne mal un
canal. Deux navigateurs réels sortant l'un et l'autre d'une adresse d'hébergeur rendent des
verdicts opposés sur deux des trois sites comparables. Une mesure qui déclare son canal
« navigateur cloud » sans nommer son fournisseur n'est donc guère plus reproductible qu'une
mesure qui ne déclare rien.

### 5.2 Le canal HTTP datacenter n'est pas non plus homogène

Le protocole demandait de ne pas re-mesurer ce canal. Je l'ai tout de même mesuré, pour
deux raisons. D'abord l'appariement : comparer une cellule du 15 août à trois cellules du
16 aurait mêlé l'effet de canal à la dérive des sites, alors que le protocole exige
lui-même que les quatre cellules soient prises dans la même fenêtre de temps. Ensuite la
provenance : la campagne du 15 août est sortie par un proxy d'egress interceptant, qui
répondait à la place des sites. Le serveur de cette campagne n'en a pas.

Les observations du 15 août ne sont ni écrasées ni modifiées.

| Site | 15/08, datacenter **avec** proxy d'egress | 16/08, datacenter **sans** proxy | Écart |
|---|---|---|---|
| Allrecipes | `paywall_402` | `forbidden_403` | **change** |
| Amazon | `antibot_challenge` | `antibot_challenge` | identique |
| Apple | `ok` | `ok` | identique |
| ArXiv | `ok` | `ok` | identique |
| BBC News | `ok` | `ok` | identique |
| Booking | `antibot_challenge` | `antibot_challenge` | identique |
| Cambridge Dictionary | `ok` | `ok` | identique |
| Coursera | `ok` | `ok` | identique |
| ESPN | `antibot_challenge` | `forbidden_403` | **change** |
| GitHub | `channel_blocked` | `ok` | **change** |
| Google Flights | `ok` | `ok` | identique |
| Google Map | `ok` | `ok` | identique |
| Google Search | `ok` | `ok` | identique |
| Huggingface | `ok` | `ok` | identique |
| Wolfram Alpha | `ok` | `ok` | identique |

Trois signatures changent, mais une seule change de verdict d'accès, et c'est la seule sur
laquelle je conclus. GitHub passe de `channel_blocked` à `ok` : la réponse du 15 août venait
du proxy et non du site, la couche L2 avait donc raison de refuser de l'imputer au site, et
l'exclusion des 41 tâches GitHub du calcul de decay était le bon choix. Les deux autres
sites restent des refus et ne changent que de forme ; comme une journée a passé et que la
machine a changé, la campagne ne permet pas de dire ce qui revient au proxy.

Ce constat garde néanmoins une portée. L'étiquette `http_datacenter` recouvre elle aussi
des canaux différents selon qu'un intermédiaire s'interpose ou non, et le vocabulaire du
mémoire ne le distingue pas.

## 6. Répétabilité, et sensibilité au faux positif

| Cellule | Sites comparés | Signatures changées | Taux | Lesquelles |
|---|---|---|---|---|
| HTTP · datacenter | 15 | **0** | 0.0 | aucune |
| HTTP · résidentiel | 15 | **1** | 0.0667 | Allrecipes : ok → forbidden_403 |
| Navigateur · résidentiel | 15 | **0** | 0.0 | aucune |
| Navigateur · datacenter | 15 | **1** | 0.0667 | Allrecipes : antibot_challenge → forbidden_403 |

Sur les soixante paires de signatures comparables entre les deux passes, deux changent, et
les deux concernent le même site. Quatorze sites sur quinze rendent exactement la même
signature dans les quatre cellules à une heure d'intervalle. La mesure est donc stable, et
c'est ce qui permet d'attribuer les écarts entre cellules au canal plutôt qu'au bruit.

Cette stabilité rend le cas d'Allrecipes d'autant plus notable. Ce site n'oscille pas entre
deux états au fil des requêtes : il a changé d'état dans deux cellules à la fois. Deux
mesures ne permettent pas d'en déduire une fréquence, et je ne sais donc pas si un
observateur qui sonderait ce site une seule fois aurait une chance sur deux de se tromper
ou beaucoup moins. Ce qu'elles établissent, c'est qu'une seule mesure ne suffit pas à
décrire ce site.

La conclusion pratique dépasse ce site. Le dossier disposait jusqu'ici d'un re-sondage à
trois minutes et d'un autre à vingt-quatre heures, tous deux sur le seul canal HTTP, et tous
deux stables. Ils avaient donc conduit à traiter la stabilité comme acquise. Une heure
suffit à trouver un contre-exemple dès qu'on regarde plusieurs canaux.

Une seconde forme de sensibilité mérite d'être publiée, puisque la section 5 a montré que
le verdict rendu sur Wolfram Alpha est un artefact du classifieur. Le tableau suivant
reprend l'analyse en retirant ce site. Les données ne sont pas modifiées : le verdict du
classifieur reste ce qu'il est dans les fichiers, et c'est l'analyse qui est refaite sans
lui.

_Analyse refaite sans Wolfram Alpha, sur 14 sites. Les données ne sont pas modifiées._

| Grandeur | Avec tous les sites | Sans le site exclu |
|---|---|---|
| Bascules de moteur (origine résidentielle), passe 1 | 4 / 15 | 3 / 14 |
| Bascules de moteur (origine datacenter), passe 1 | 3 / 15 | 2 / 14 |
| Bascules d'origine (moteur HTTP), passe 1 | 1 / 15 | 1 / 14 |
| Bascules d'origine (moteur navigateur), passe 1 | 2 / 15 | 2 / 14 |
| κ de Cohen, HTTP · datacenter ↔ HTTP · résidentiel, passe 1 | 0.8148 | 0.8108 |
| κ de Cohen, HTTP · datacenter ↔ Navigateur · résidentiel, passe 1 | -0.1194 | 0.0 |
| κ de Cohen, HTTP · datacenter ↔ Navigateur · datacenter, passe 1 | 0.4444 | 0.5882 |
| κ de Cohen, HTTP · résidentiel ↔ Navigateur · résidentiel, passe 1 | -0.1111 | 0.0 |
| κ de Cohen, HTTP · résidentiel ↔ Navigateur · datacenter, passe 1 | 0.1667 | 0.2759 |
| κ de Cohen, Navigateur · résidentiel ↔ Navigateur · datacenter, passe 1 | 0.4444 | 0.0 |
| Bascules de moteur (origine résidentielle), passe 2 | 5 / 15 | 4 / 14 |
| Bascules de moteur (origine datacenter), passe 2 | 3 / 15 | 2 / 14 |
| Bascules d'origine (moteur HTTP), passe 2 | 0 / 15 | 0 / 14 |
| Bascules d'origine (moteur navigateur), passe 2 | 2 / 15 | 2 / 14 |
| κ de Cohen, HTTP · datacenter ↔ HTTP · résidentiel, passe 2 | 1.0 | 1.0 |
| κ de Cohen, HTTP · datacenter ↔ Navigateur · résidentiel, passe 2 | -0.1194 | 0.0 |
| κ de Cohen, HTTP · datacenter ↔ Navigateur · datacenter, passe 2 | 0.4444 | 0.5882 |
| κ de Cohen, HTTP · résidentiel ↔ Navigateur · résidentiel, passe 2 | -0.1194 | 0.0 |
| κ de Cohen, HTTP · résidentiel ↔ Navigateur · datacenter, passe 2 | 0.4444 | 0.5882 |
| κ de Cohen, Navigateur · résidentiel ↔ Navigateur · datacenter, passe 2 | 0.4444 | 0.0 |

## 7. Ce que cela change pour le mémoire

**1. κ ne doit plus être écrit sans nommer le canal qui juge.** La même cellule
`http_datacenter` obtient une crédibilité qui va de 0,17 à 0,83 selon le canal auquel on la
confronte. La correction à apporter au chapitre 3 n'est pas un nouveau nombre, dont
l'effectif ne permettrait de toute façon pas de le distinguer de l'ancien, mais une
notation : κ(accusé, juge), et la mention explicite du juge dans la configuration canonique
de l'annexe A.

**2. La nomenclature des canaux est incomplète de deux dimensions.** Le mémoire décrit un
canal par son moteur de rendu et son origine réseau. Il y manque la présence d'un
intermédiaire, puisque le retrait du proxy d'egress fait passer GitHub de `channel_blocked`
à `ok`, et l'identité du fournisseur, puisque deux navigateurs sortant tous deux d'une
adresse d'hébergeur divergent sur deux des trois sites comparables. Deux équipes qui
déclarent le même canal au sens actuel peuvent donc publier des chiffres non comparables.

**3. La longueur de l'extrait classifié est un paramètre de mesure, pas un détail
d'implémentation.** Le cas Wolfram Alpha montre qu'elle peut à elle seule faire diverger
deux canaux qui voient la même page, et le cas Allrecipes qu'un défi Cloudflare de 330 ko
passe entièrement sous le radar d'un extrait de 4 000 caractères. Or ce paramètre
n'apparaît nulle part dans le mémoire : ni au chapitre 3, ni dans la fiche de configuration
canonique de l'annexe A, alors que celle-ci consigne κ. Il n'est documenté que dans une
docstring du paquet. Une variable dont dépend le verdict devrait figurer dans la
configuration publiée au même titre que κ, sans quoi deux exécutions de l'outil réglées
différemment produiront des chiffres qu'on croira comparables.

## 8. Limites

Ces limites sont écrites contre le résultat, parce qu'une limite trouvée par le jury coûte
plus cher qu'une limite reconnue par l'auteur.

**La faiblesse principale est bornée, pas levée.** Le mémoire définit sa fragilité comme le
fait que κ = 0,40 repose sur trois observations Browserbase non reproductibles. Faute de
compte, je n'ai pas pu re-mesurer Browserbase. Ces trois observations restent donc
exactement aussi peu reproductibles qu'avant. Ce que la campagne apporte est un plan
identifiable, une mesure rejouable et un ordre de grandeur ; elle ne remplace pas la mesure
manquante.

**Quinze sites restent quinze sites, et l'effectif interdit le classement.** Quatre sites
basculent sous l'effet du moteur, deux sous l'effet de l'origine. Le test exact de Fisher ne
permet pas de distinguer ces deux nombres. Sur les κ de crédibilité, la résolution du
dispositif est d'un sixième par site.

**L'adresse résidentielle est une adresse mobile.** Elle appartient à AS51207 Free Mobile,
c'est-à-dire à un réseau mobile dont les abonnés partagent des adresses publiques par
traduction d'adresses à grande échelle. Sa réputation auprès des dispositifs anti-robot
n'est pas celle d'une ligne fixe, et elle n'est pas non plus celle d'une autre adresse
mobile. Un seul point a été échantillonné, sur un seul opérateur, dans un seul pays.

**Le contraste d'origine n'isole pas la réputation de l'adresse.** Les points de présence
atteints diffèrent, les éditions localisées servies diffèrent, et les systèmes
d'exploitation des deux machines diffèrent, macOS d'un côté et Linux de l'autre, ce que
l'User-Agent annonce. Ces trois facteurs sont confondus avec l'origine réseau. C'est le
défaut de plan que je n'ai pas pu éliminer, et il limite l'interprétation de la ligne
« origine » du tableau 2.

**Le contraste de moteur ne fait pas varier que le moteur.** Le canal HTTP présente
l'User-Agent d'un Chrome 128, celui du profil « browser » du paquet, tandis que les
cellules navigateur présentent celui de leur Chrome 148 réel. Vingt versions majeures
séparent les deux, et un dispositif de filtrage peut en tenir compte.

**Le classifieur a été pris tel quel, avec ses défauts.** Quatre lui sont apparus pendant la
campagne, décrits en annexe A, et l'un d'eux a produit un faux positif qui a coûté à ce
rapport une conclusion entière. Je ne les ai pas corrigés, parce que changer les règles en
cours de campagne aurait rendu les quatre cellules incomparables et incomparables aux
mesures du 15 août. Les verdicts publiés ici héritent donc de ces défauts.

**Le contrôle `meta.page_reelle_affichee` n'est pas indépendant du classifieur.** Il
réutilise les mêmes expressions de détection, si bien que sur une observation tranchée par
un marqueur, il ne peut structurellement que confirmer le verdict. Le seul contrôle
réellement indépendant est la capture d'écran, et c'est elle qui a révélé le faux positif
de Wolfram Alpha.

**Cinq robots.txt sont ambigus.** Sur allrecipes.com, amazon.com, bbc.com, espn.com et
wolframalpha.com, la racine est autorisée au groupe `User-agent: *`, mais le fichier
interdit explicitement `/` à des agents d'intelligence artificielle nommés. Mon client ne se
déclare sous aucun de ces noms et respecte donc la lettre du fichier, mais pas l'intention
que ces lignes expriment. Je l'ai fait quand même, pour une requête par site et par passe
sur une page d'accueil publique, sans extraction de contenu. Aucune cible n'était interdite
au sens strict, et le `Crawl-delay: 15` d'arxiv.org a été respecté.

**Deux passes en une heure ne disent rien du long terme.** La répétabilité mesurée ici borne
la fluctuation à l'échelle de l'heure. Elle ne dit rien de ce que ces quinze sites
répondront dans six mois, qui est pourtant la question du mémoire.

**La campagne a pu provoquer le seul changement qu'elle observe.** Allrecipes a été sollicité
quatre fois en une heure depuis la même adresse résidentielle, et c'est le seul site dont la
signature change entre les deux passes. Je ne peux pas exclure que le blocage constaté à la
seconde passe soit une réaction à la première. Une campagne qui mesure des dispositifs
anti-robot est un objet qui perturbe ce qu'il observe, et le protocole choisi, une requête
par site et par passe, limite cette perturbation sans la supprimer.

**Une seule mesure par case et par passe.** Aucun vote, aucune moyenne. Un site qui alterne
ses réponses est vu une fois par passe, pas caractérisé.

## Annexe A. Ce que le protocole a dû corriger en route

Le protocole qui m'a été transmis venait d'une lecture de la documentation, pas d'une
exécution. J'ai donc commencé par établir la surface réelle de l'outil, et plusieurs
corrections ont suivi.

**Ce qui existait bien.** Contrairement à ce que le protocole envisageait, le drapeau
`--allowed-domains` existe, de même que `network har start/stop`, `network requests --json`
et `network request <id>`. La seule commande introuvable est un prétendu skill « cloud
browser » générique : il n'y en a pas, la documentation des cinq fournisseurs se trouve dans
le README du paquet.

**Le confinement de domaines a été retiré du protocole principal.** C'est la correction qui
va le plus directement contre une consigne explicite. Le protocole demandait de passer
`--allowed-domains` pour se contraindre matériellement. Appliqué, ce drapeau fabrique des
refus. Comparé à la mesure sans confinement, il change quatre verdicts sur quinze :
`dictionary.cambridge.org` devient `unreachable` faute de rendre son DOM, Google Flights et
Google Maps passent de `ok` à `forbidden_403`, et Amazon de `ok` à `antibot_challenge`. Le
drapeau bloque les ressources tierces dont ces pages ont besoin pour s'afficher, si bien
qu'il mesure le confinement plutôt que le site. Quatre faux refus sur quinze, c'est plus que
l'effet que la campagne cherche à mesurer. J'ai donc mesuré sans confinement et conservé la
mesure confinée comme analyse de sensibilité, dans
`runs/matrice/browser_residential_p1_confine.json`. La contrainte d'accès tient au script,
qui n'émet qu'une navigation par site, sans clic ni saisie ni navigation interne.

**Le navigateur tourne avec fenêtre et non sans affichage.** En mode sans affichage, Chrome
annonce `HeadlessChrome` dans son User-Agent. Mesurer ainsi reviendrait à se signaler comme
robot au moment même où l'on mesure la façon dont les sites traitent les robots. Le mode
avec fenêtre présente l'User-Agent authentique du navigateur, sans rien maquiller.

**Quatre défauts du classifieur sont apparus, et n'ont pas été corrigés.**

1. La règle du code 202 est évaluée avant le corps : un défi résolu par le navigateur reste
   classé `antibot_challenge` parce que la réponse initiale portait ce code. C'est ce qui
   explique l'étiquette de Booking dans la mesure du 15 août.
2. La longueur de l'extrait classifié laisse passer les interstitiels volumineux. Le défi
   Cloudflare Turnstile servi à Allrecipes pèse 330 ko et son marqueur tombe au-delà de la
   coupure.
3. Ce même défi n'est de toute façon pas détectable dans le corps réseau, parce que son
   marqueur y est injecté par JavaScript. Un canal sans navigateur est structurellement
   incapable de le voir.
4. La détection de CAPTCHA se déclenche sur une chaîne de configuration. `"captchaApi"`
   dans un objet JavaScript suffit à faire classer `captcha` une page d'accueil normale,
   comme le montre le cas Wolfram Alpha.

J'ai laissé le classifieur trancher et enregistré à côté un contrôle, dans
`meta.page_reelle_affichee` et `meta.defi_dans_corps_reseau_integral`, dont la section 8
rappelle qu'il n'est pas indépendant.

**Trois défauts de collecte ont été corrigés.** Le protocole de débogage de Chrome ne rend
pas toujours le corps du document ; il revenait vide, et le classifieur y lisait un
`soft_404`, c'est-à-dire une page morte imputée au site. Le corps a été relu dans les HAR.
Une lecture de DOM revenue vide est désormais retentée puis déclarée invalide plutôt que
classée. Enfin, la première version du collecteur retenait la dernière requête de type
Document comme document principal, ce qui attrapait parfois une iframe tierce, bandeau de
consentement ou ancre reCAPTCHA, et publiait son statut à la place de celui du site ; la
règle corrigée retient l'URL de la page finale, et `meta.document_principal_url` porte
désormais le document retenu.

**Les cellules en centre de données ont été mesurées sur un serveur loué.** Aucune clé de
fournisseur de navigateurs cloud n'était disponible. Un serveur OVH en France donne la même
chose sur le plan expérimental, une adresse d'hébergeur et un Chrome réel, avec l'avantage
d'être reproductible sans compte payant. Chrome y a été aligné sur la version 148 utilisée
localement, et lancé avec `--no-sandbox` parce que les espaces de noms utilisateur sont
désactivés sur cette machine ; ce drapeau ne change ni l'empreinte réseau ni l'User-Agent.
Une variante par runner GitHub Actions est fournie pour qui n'a pas de serveur.

## Annexe B. Reproduire la campagne

```bash
# cellules résidentielles, depuis une machine derrière un abonnement grand public
./experiments/campagne_matrice.sh --passe 1 --cellules residentielles
./experiments/campagne_matrice.sh --passe 2 --cellules residentielles   # au moins 1 h après

# cellules datacenter, depuis un serveur loué
./experiments/campagne_matrice.sh --passe 1 --cellules datacenter
./experiments/campagne_matrice.sh --passe 2 --cellules datacenter

# analyse, consolidation, rapport
./experiments/campagne_matrice.sh --analyse
python experiments/consolider_matrice.py --runs runs/matrice \
    --sortie runs/l2_matrice_canaux_20260816.json
python experiments/rendre_rapport_canaux.py --runs runs/matrice \
    --gabarit experiments/RAPPORT_CANAUX_gabarit.md \
    --sortie experiments/RAPPORT_CANAUX.md
```

Une variante sans serveur loué est fournie dans
`.github/workflows/matrice_canaux_datacenter.yml` : un runner GitHub Actions offre lui aussi
une adresse d'hébergeur et un navigateur réel, gratuitement.

Les tableaux de ce rapport sont produits par `experiments/rendre_rapport_canaux.py` à partir
des fichiers de `runs/matrice/`, et le texte est assemblé autour d'eux. Les chiffres cités
dans les phrases, eux, sont écrits à la main et peuvent donc se désynchroniser des tableaux
si la campagne est rejouée : ils sont à relire avant toute republication.
