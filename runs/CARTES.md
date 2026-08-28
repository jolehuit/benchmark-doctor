# Les cartes de `runs/` — laquelle citer

Ce dépôt contient dix cartes de santé et deux artefacts de sensibilité. Elles ne se
contredisent pas : ce sont des **configurations différentes du même outil**. Le
problème corrigé le 16/08/2026 n'était pas un problème de calcul mais de rédaction —
aucune n'était déclarée comme la référence, et le README publiait une carte pendant
que les tables de sensibilité en publiaient une autre (`VERIFICATION.md` §C8).

**Une seule carte est citable dans le mémoire.** Les autres sont sur le disque parce
qu'elles servent à quelque chose — un différentiel, une ablation — pas parce qu'elles
sont des états concurrents du benchmark.

Chaque JSON porte désormais son propre verdict dans un champ `statut_editorial` en
tête de fichier. Cet index est écrit par `experiments/marquer_cartes.py`.

## 1. Carte canonique — la seule citable

| Fichier | Date | Configuration | Stabilité ⌀ | A / B / C / D |
|---|---|---|---:|---|
| `health_20260815.json` | 2026-08-15 | L1+L2+L3 +solv · gemini-2.5-flash:rubric | 0.5851 | 210 / 138 / 185 / 110 |
| `carte_canonique_20260815.json` | 2026-08-15 | L1+L2+L3 +solv · gemini-2.5-flash:rubric | 0.5851 | 210 / 138 / 185 / 110 |

Configuration, en toutes lettres : corpus `data/raw/webvoyager_original.jsonl`
(643 tâches, sha256 69b19fd8…c488) · date de référence **gelée au 2026-08-15** ·
couches **L1 + L2 + L3, solvabilité incluse** · canal L2 `direct_http:browser`
(`http_datacenter`, κ = 0,40) · contenus vérifiés · backend d'ambiguïté
**`llm-judge:gemini-2.5-flash:rubric`, seuil 0,5** · a priori des praticiens inclus
dans le score publié · échelle de notes **A > 0,75 · B > 0,50 · C > 0,25 · D ≤ 0,25**.

Elle se rejoue hors ligne, sans un appel réseau et sans un centime :

```
python3 experiments/carte_canonique.py --check
```

## 2. Configurations exploratoires — non citées

| Fichier | Date | Configuration | Stabilité ⌀ | A / B / C / D |
|---|---|---|---:|---|
| `health_card_webvoyager_llm_20260816.json` | 2026-08-16 | L1+L2+L3 · gemini-2.5-flash:rubric | 0.6377 | 239 / 155 / 180 / 69 |
| `health_card_webvoyager_20260816.json` | 2026-08-16 | L1+L2+L3 · tfidf+logreg | 0.6724 | 266 / 186 / 123 / 68 |
| `health_webvoyager_20260815.json` | 2026-08-15 | static | 0.856 | 509 / 61 / 73 / 0 |
| `scoring_model_20260816.json` | 2026-08-16 | L1+L2+L3 · gemini-2.5-flash:rubric | — | — |

## 3. Entrées de différentiels — ce ne sont pas des cartes de santé

Ces cartes existent pour être **comparées entre elles**. Leur distribution de notes
n'a pas de sens isolément : elle décrit un corpus partiel (L1 seule) ou un canal
partiel (navigateur cloud, 4 sites mesurés sur 15).

| Fichier | Date | Configuration | Stabilité ⌀ | A / B / C / D |
|---|---|---|---:|---|
| `card_direct_20260816.json` | 2026-08-16 | L1+L2 | 0.7487 | 359 / 163 / 61 / 60 |
| `card_browsercloud_20260815.json` | 2026-08-15 | L1+L2 | 0.784 | 465 / 49 / 69 / 60 |
| `card_l1_20240302.json` | 2024-03-02 | L1 | 0.8771 | 525 / 71 / 46 / 1 |
| `card_l1_20260816.json` | 2026-08-16 | L1 | 0.85 | 509 / 61 / 69 / 4 |
| `card_magnitude_20250706.json` | 2025-07-06 | L1 | 0.9244 | 524 / 64 / 2 / 0 |
| `card_magnitude_20260816.json` | 2026-08-16 | L1 | 0.8579 | 477 / 51 / 62 / 0 |

## 4. Le piège à éviter, nommément

Coller dans le même paragraphe « stabilité moyenne 0,585 » (carte canonique) et
« κ = 1 → 144 tâches en note D » (table du rapport 5) est **factuellement faux** :
les deux chiffres viennent de configurations différentes. Dans la configuration
canonique, κ = 1 donne **177** tâches en D. La table canonique est publiée dans
`runs/carte_canonique_20260815.json`, section `sensibilite_kappa`.
