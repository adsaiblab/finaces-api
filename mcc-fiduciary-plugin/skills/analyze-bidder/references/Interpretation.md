# Guide d'Interprétation Fiduciaire (MCC-Grade)

Ce guide définit les règles d'interprétation des ratios financiers.
Tu DOIS utiliser exclusivement les labels suivants :
**VALID_LABELS** = ["INSUFFISANT", "FAIBLE", "MODERE", "FORT", "TRES_FORT"]

## 1. Liquidité (Capacité à court terme)

- **Current Ratio** : < 0.8 (INSUFFISANT), 0.8-1.0 (FAIBLE), 1.0-1.5 (MODERE), 1.5-2.0 (FORT), > 2.0 (TRES_FORT)
- **Quick Ratio** : < 0.5 (INSUFFISANT), 0.5-0.8 (FAIBLE), 0.8-1.0 (MODERE), 1.0-1.5 (FORT), > 1.5 (TRES_FORT)

## 2. Solvabilité (Structure financière à long terme)

- **Autonomie Financière** : < 0.10 (INSUFFISANT), 0.10-0.15 (FAIBLE), 0.15-0.35 (MODERE), 0.35-0.50 (FORT), > 0.50 (TRES_FORT)
- **Gearing (Debt-to-Equity)** : > 3.0 (INSUFFISANT), 2.0-3.0 (FAIBLE), 1.0-2.0 (MODERE), 0.5-1.0 (FORT), < 0.5 (TRES_FORT)

## 3. Rentabilité (Performance d'exploitation)

- **Marge Nette** : < 0% (INSUFFISANT), 0-1% (FAIBLE), 1-5% (MODERE), 5-10% (FORT), > 10% (TRES_FORT)
- **ROE** : < 0% (INSUFFISANT), 0-5% (FAIBLE), 5-10% (MODERE), 10-15% (FORT), > 15% (TRES_FORT)

## 4. Analyse Dynamique (Cross-Pillar)

Vérifie toujours les relations transversales :

- Croissance du CA vs. BFR (Effet ciseaux)
- Rentabilité vs. Cash Conversion Cycle
Toute incohérence détectée doit faire l'objet d'un commentaire justifié de ta part et documenté via write_interpretation.
