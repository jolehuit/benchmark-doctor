# Les cartes de `runs/`

Douze fichiers de `runs/` publient une distribution de notes : dix cartes de santé
et deux artefacts de sensibilité. Une seule est citée dans le mémoire,
`health_20260815.json`. Chaque JSON porte son statut et sa raison en tête de
fichier, dans le champ `statut_editorial`. Cet index est écrit par
`experiments/marquer_cartes.py`.

| Fichier | Statut | Date | Configuration | Stabilité moyenne | A / B / C / D |
|---|---|---|---|---:|---|
| `health_20260815.json` | canonique | 2026-08-15 | L1+L2+L3 +solv, gemini-2.5-flash:rubric | 0.5851 | 210 / 138 / 185 / 110 |
| `carte_canonique_20260815.json` | canonique | 2026-08-15 | L1+L2+L3 +solv, gemini-2.5-flash:rubric | 0.5851 | 210 / 138 / 185 / 110 |
| `health_card_webvoyager_llm_20260816.json` | exploratoire | 2026-08-16 | L1+L2+L3, gemini-2.5-flash:rubric | 0.6377 | 239 / 155 / 180 / 69 |
| `health_card_webvoyager_20260816.json` | exploratoire | 2026-08-16 | L1+L2+L3, tfidf+logreg | 0.6724 | 266 / 186 / 123 / 68 |
| `health_webvoyager_20260815.json` | exploratoire | 2026-08-15 | static | 0.856 | 509 / 61 / 73 / 0 |
| `scoring_model_20260816.json` | exploratoire | 2026-08-16 | L1+L2+L3, gemini-2.5-flash:rubric | - | - |
| `card_direct_20260816.json` | entrée de différentiel | 2026-08-16 | L1+L2 | 0.7487 | 359 / 163 / 61 / 60 |
| `card_browsercloud_20260815.json` | entrée de différentiel | 2026-08-15 | L1+L2 | 0.784 | 465 / 49 / 69 / 60 |
| `card_l1_20240302.json` | entrée de différentiel | 2024-03-02 | L1 | 0.8771 | 525 / 71 / 46 / 1 |
| `card_l1_20260816.json` | entrée de différentiel | 2026-08-16 | L1 | 0.85 | 509 / 61 / 69 / 4 |
| `card_magnitude_20250706.json` | entrée de différentiel | 2025-07-06 | L1 | 0.9244 | 524 / 64 / 2 / 0 |
| `card_magnitude_20260816.json` | entrée de différentiel | 2026-08-16 | L1 | 0.8579 | 477 / 51 / 62 / 0 |

## Configuration canonique

Corpus `data/raw/webvoyager_original.jsonl`, 643 tâches, sha256 69b19fd8…c488.
Date de référence gelée au 2026-08-15. Couches L1 + L2 + L3, solvabilité incluse.
Canal L2 `direct_http:browser` (`http_datacenter`, κ = 0,40), contenus vérifiés.
Backend d'ambiguïté `llm-judge:gemini-2.5-flash:rubric`, seuil 0,5. A priori des
praticiens inclus dans le score publié. Échelle de notes A > 0,75, B > 0,50,
C > 0,25, D ≤ 0,25.

Le rejeu hors ligne de cette carte et de ses tables de sensibilité :

```
python3 experiments/carte_canonique.py --check
```
