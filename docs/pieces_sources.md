# Pièces sources : les 19 dépôts relevés et les 121 correctifs de Magnitude

Deux relevés que j'ai établis moi-même et que je reproduis ici pour qu'ils se recomptent ligne à
ligne.

## Maintenance des 19 dépôts au 15 août 2026

J'ai cloné les 19 dépôts et compté leurs commits ; aucun de ces comptes n'est publié par les
équipes. Le statut se lit dans les deux colonnes : gelé vaut zéro commit sur douze mois, quasi
inerte un seul, inactif au moins un sur douze mois et aucun sur six, ralenti un à cinq sur six
mois, actif six à cent, très actif plus de cent, semi-actif le seul dépôt dont le compte à six mois
manque. La colonne Panel dit si la ligne est l'un des 13 benchmarks de
`docs/panel_treize_benchmarks.md`. Le décompte donne 11 dépôts inertes ou quasi inertes sur 19.

| Dépôt | Benchmark | Dernier commit | 12 mois | 6 mois | Statut au 15/08/2026 | Panel |
|---|---|---|---:|---:|---|---|
| MinorJerry/WebVoyager | WebVoyager | 04/03/2024 | 0 | 0 | Gelé | oui |
| jykoh/visualwebarena | VisualWebArena | 08/11/2024 | 0 | 0 | Gelé | non |
| oriyor/assistantbench | AssistantBench | 09/12/2024 | 0 | 0 | Gelé | oui |
| iMeanAI/WebCanvas | Mind2Web-Live / WebCanvas | 06/02/2025 | 0 | 0 | Gelé | oui |
| agi-inc/REAL | REAL (dépôt vitrine) | 15/05/2025 | 0 | 0 | Gelé | oui |
| Halluminate/WebBench | WebBench | 29/07/2025 | 0 | 0 | Gelé | oui |
| OSU-NLP-Group/Mind2Web | Mind2Web | 04/11/2025 | 1 | 0 | Quasi inerte | non |
| web-arena-x/webarena | WebArena | 26/11/2025 | 38 | 0 | Inactif | oui |
| agi-inc/agisdk | REAL (code exécutable) | 05/12/2025 | non relevé | 0 | Inactif | oui |
| ServiceNow/WorkArena | WorkArena | 03/02/2026 | 78 | 0 | Inactif | non |
| ServiceNow/webarena-verified | WebArena-Verified | 07/02/2026 | 22 | 0 | Inactif | oui |
| OSU-NLP-Group/Mind2Web-2 | Mind2Web 2 | 17/02/2026 | 47 | 3 | Ralenti | oui |
| web-arena-x/webarena-infinity | WebArena-Infinity | 23/03/2026 | non relevé | 252 | Très actif | non |
| EmergenceAI/EmergenceWebVoyager | Emergence WebVoyager | 23/04/2026 | 8 | non relevé | Semi-actif | oui |
| facebookresearch/are | ARE / Gaia2 | 21/05/2026 | 29 | 9 | Actif | non |
| OSU-NLP-Group/Online-Mind2Web | Online-Mind2Web | 28/05/2026 | 14 | 7 | Actif | oui |
| xlang-ai/OSWorld | OSWorld | 28/07/2026 | 165 | 77 | Actif | oui |
| yutori-ai/navi-bench | Navi-Bench | 09/08/2026 | non relevé | 205 | Très actif | oui |
| xlang-ai/OSWorld-V2 | OSWorld 2.0 | 14/08/2026 | non relevé | 353 | Très actif | oui |

`agi-inc/REAL` porte trois commits et le code vit dans `agi-inc/agisdk` : ces deux lignes valent un
benchmark, ce qui fait 18 benchmarks pour 19 dépôts. Les cinq comptes non relevés n'entrent pas
dans le décompte des 11, dont chaque ligne porte un zéro mesuré.

## Les 121 correctifs de Magnitude dans la taxonomie

Magnitude est le seul patch-set publié qui motive en texte libre chacune de ses décisions. J'ai lu
un à un les 121 motifs de sa version du 6 juillet 2025 et je les ai rangés dans les huit catégories
de la taxonomie. Ce classement vient d'un annotateur unique, moi, sans seconde lecture ni accord
inter-annotateurs, et 16 des 121 décisions portent une marque de cas frontalier (dérive de contenu
9, accès refusé 3, instabilité d'interface 3, dérive temporelle 1) : les parts ci-dessous ne se
lisent pas comme des taux de prévalence.

Ventilation par catégorie principale et par décision.

| Catégorie | Réécrites | Retirées | Total | Part |
|---|---:|---:|---:|---:|
| T1 dérive temporelle | 68 | 2 | 70 | 57,9 % |
| T2 dérive de contenu | 0 | 21 | 21 | 17,4 % |
| T3 accès refusé | 0 | 11 | 11 | 9,1 % |
| T4 instabilité d'interface | 0 | 7 | 7 | 5,8 % |
| T8 dépendances temporelles | 0 | 7 | 7 | 5,8 % |
| T5 ambiguïté de l'énoncé | 0 | 5 | 5 | 4,1 % |
| T6 solutions multiples | 0 | 0 | 0 | 0 % |
| T7 fragilité de l'évaluation | 0 | 0 | 0 | 0 % |
| Total | 68 | 53 | 121 | 100 % |

Une seconde catégorie est invoquée par 22 motifs, comptée en co-occurrence : T1 7 fois, T2 5, T4
4, T8 3, T5 2, T7 1.

Ventilation croisée par site.

| Site | T1 | T2 | T3 | T4 | T5 | T6 | T7 | T8 | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Allrecipes | 0 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 5 |
| Amazon | 0 | 1 | 0 | 1 | 0 | 0 | 0 | 1 | 3 |
| Apple | 4 | 4 | 1 | 1 | 2 | 0 | 0 | 0 | 12 |
| ArXiv | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| BBC News | 1 | 4 | 0 | 0 | 1 | 0 | 0 | 2 | 8 |
| Booking | 29 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 33 |
| Coursera | 0 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 2 |
| ESPN | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 7 |
| GitHub | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 2 |
| Google Flights | 31 | 1 | 2 | 0 | 0 | 0 | 0 | 0 | 34 |
| Google Map | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 3 |
| Google Search | 1 | 0 | 1 | 1 | 1 | 0 | 0 | 0 | 4 |
| Huggingface | 0 | 4 | 0 | 2 | 1 | 0 | 0 | 0 | 7 |
| Total | 70 | 21 | 11 | 7 | 5 | 0 | 0 | 7 | 121 |

Google Flights (31) et Booking (29) portent 60 des 70 tâches de dérive temporelle, l'un et l'autre
codant des dates en dur dans leurs énoncés.

Six motifs publiés, un par catégorie servie, dans le texte original de l'auteur du patch-set.

| Tâche | Décision | T | Motif publié |
|---|---|---|---|
| Apple--4 | réécrite | T1 | « The M3 Max chip, current in March 2024, will be superseded by June 2025. » |
| Allrecipes--16 | retirée | T2 | « DNE » (*does not exist*) |
| Apple--9 | retirée | T3 | « Cannot schedule actual, in-store pickup » |
| Amazon--4 | retirée | T4 | « Can't filter by 'Used - Good' from the search results page » |
| Apple--14 | retirée | T5 | « Ambiguous task, multiple M4 chip models exist » |
| Amazon--19 | retirée | T8 | « No books on this topic being released within a month » |

Le relevé des 121 lignes, avec pour chacune l'identifiant de tâche, la décision, les catégories
principale et secondaire, la marque de cas frontalier, le motif publié in extenso et le commentaire
de classement, est dans `benchmark_doctor/ground_truth/magnitude_reason_labels.json`, d'où se
recomptent les ventilations ci-dessus.
