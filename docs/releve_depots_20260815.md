# Relevé des dix-neuf dépôts de benchmarks et de leur statut de maintenance

Relevé au 15 août 2026. Ce document est la pièce source du décompte « onze dépôts inertes ou
quasi inertes sur dix-neuf » cité au chapitre 1 du mémoire.

Les comptes de commits sont des relevés de l'auteur au 15 août 2026 par clonage git, et non des données publiées. Le mémoire n'imprime que treize benchmarks
dans ses tableaux 1.1 et 1.2 ; le relevé complet est reproduit ici pour que le décompte des
onze dépôts inertes ou quasi inertes puisse être refait ligne à ligne. La dernière colonne indique si la ligne
apparaît dans les tableaux du chapitre 1.

Le statut est mécanique et se lit dans les deux colonnes de commits : **gelé** vaut zéro commit sur douze
mois, **quasi inerte** un seul, **inactif** au moins un commit sur douze mois mais aucun sur six,
**ralenti** un à cinq commits sur six mois, **actif** six à cent, **très actif** plus de cent. « Semi-actif »
désigne le seul dépôt dont le compte à six mois n'a pas été relevé.

| Dépôt | Benchmark | Dernier commit | 12 mois | 6 mois | Statut au 15/08/2026 | Ch. 1 |
|---|---|---|---:|---:|---|---|
| MinorJerry/WebVoyager | WebVoyager | 04/03/2024 | 0 | 0 | **Gelé** | oui |
| jykoh/visualwebarena | VisualWebArena | 08/11/2024 | 0 | 0 | **Gelé** | non |
| oriyor/assistantbench | AssistantBench | 09/12/2024 | 0 | 0 | **Gelé** | oui |
| iMeanAI/WebCanvas | Mind2Web-Live / WebCanvas | 06/02/2025 | 0 | 0 | **Gelé** | oui |
| agi-inc/REAL | REAL (dépôt vitrine) | 15/05/2025 | 0 | 0 | **Gelé** | oui |
| Halluminate/WebBench | WebBench | 29/07/2025 | 0 | 0 | **Gelé** | oui |
| OSU-NLP-Group/Mind2Web | Mind2Web | 04/11/2025 | 1 | 0 | **Quasi inerte** | non |
| web-arena-x/webarena | WebArena | 26/11/2025 | 38 | 0 | **Inactif** | oui |
| agi-inc/agisdk | REAL (code exécutable) | 05/12/2025 | non relevé | 0 | **Inactif** | oui |
| ServiceNow/WorkArena | WorkArena | 03/02/2026 | 78 | 0 | **Inactif** | non |
| ServiceNow/webarena-verified | WebArena-Verified | 07/02/2026 | 22 | 0 | **Inactif** | oui |
| OSU-NLP-Group/Mind2Web-2 | Mind2Web 2 | 17/02/2026 | 47 | 3 | Ralenti | oui |
| web-arena-x/webarena-infinity | WebArena-Infinity | 23/03/2026 | non relevé | 252 | Très actif | non |
| EmergenceAI/EmergenceWebVoyager | Emergence WebVoyager | 23/04/2026 | 8 | non relevé | Semi-actif | oui |
| facebookresearch/are | ARE / Gaia2 | 21/05/2026 | 29 | 9 | Actif | non |
| OSU-NLP-Group/Online-Mind2Web | Online-Mind2Web | 28/05/2026 | 14 | 7 | Actif | oui |
| xlang-ai/OSWorld | OSWorld | 28/07/2026 | 165 | 77 | Actif | oui |
| yutori-ai/navi-bench | Navi-Bench | 09/08/2026 | non relevé | 205 | Très actif | oui |
| xlang-ai/OSWorld-V2 | OSWorld 2.0 | 14/08/2026 | non relevé | 353 | Très actif | oui |

**Le décompte, pour qu'il puisse être refait.** Six dépôts sont gelés, un est quasi inerte, quatre sont
inactifs depuis six mois : **onze sur dix-neuf**, chiffre repris au 1.1. Les huit autres se répartissent en un
ralenti, un semi-actif, trois actifs et trois très actifs.

**La réserve qui accompagne ce décompte, et elle est double.** D'une part, ces dix-neuf lignes sont
dix-neuf **dépôts** et non dix-neuf benchmarks distincts : `agi-inc/REAL` ne contient que trois commits, le
code vivant en réalité dans `agi-inc/agisdk`, et les deux lignes se lisent ensemble. Le panel compte donc
dix-huit benchmarks pour dix-neuf dépôts, et le chiffre de onze inertes est à ce titre une **borne haute**.
D'autre part, quatre comptes à douze mois et un compte à six mois n'ont pas été relevés ; aucun d'eux
n'intervient dans le décompte des onze, dont chaque ligne porte un zéro mesuré.
