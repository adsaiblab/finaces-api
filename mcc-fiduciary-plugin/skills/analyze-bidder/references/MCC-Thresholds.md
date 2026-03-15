# Synthèse des Seuils Sectoriels (MCC-grade)

Ce document sert de référentiel strict pour l'ajustement de l'interprétation des ratios financiers en fonction du secteur d'activité du candidat.

L'Agent doit moduler la sévérité de son "label" (INSUFFISANT, FAIBLE, MODERE, FORT, TRES_FORT) en comparant les ratios réels aux cibles sectorielles ci-dessous.

## Matrice des Seuils Liquidité et Solvabilité

| Secteur d'activité | Ratio de Liquidité Générale (Cible) | Autonomie Financière (Capitaux Propres / Total Bilan) |
| :--- | :--- | :--- |
| **BTP & Construction** | `> 1.2` (BFR élevé structurellement) | `> 20%` (Actifs immobilisés forts) |
| **IT & Services Numériques** | `> 1.0` (Peu de stocks, recouvrement rapide) | `> 30%` (Actifs immatériels importants) |
| **Agro-industrie** | `> 1.5` (Cycle d'exploitation long) | `> 25%` (Besoins capitalistiques modérés à forts) |
| **Fournitures Standard** | `> 1.3` | `> 25%` |
| **Consulting / Intellectuel** | `> 0.9` (Peu d'engagements hors bilan) | `> 15%` |

## Consignes d'Interprétation

1. **Identification du Secteur** : Si le secteur n'est pas explicite, utilisez par défaut la ligne "Fournitures Standard".
2. **Modulation** :
   * Si une entreprise BTP a une liquidité de 1.1, c'est considéré comme "FAIBLE" (car sous la cible 1.2 du BTP).
   * Si une ESN (IT) a une liquidité de 1.1, c'est considéré comme "MODERE" à "FORT" (car au-dessus de la cible 1.0 de l'IT).
3. **Justification** : Lors de la rédaction de l'interprétation (`write_interpretation`), justifiez explicitement l'appréciation des ratios primaires en citant la cible de ce référentiel.
