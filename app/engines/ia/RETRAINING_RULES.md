# FinaCES IA — Retraining Rules & Drift Thresholds

> **Objectif** : Définir les seuils de ré-entraînement et les règles d'alerte pour détecter quand le modèle LightGBM/XGBoost dérive par rapport à la distribution originale de l'entraînement.
>
> Ce document est la référence opérationnelle pour l'équipe data science. Il n'y a **pas** de ré-entraînement automatique en production — toutes les décisions sont manuelles et auditées.

---

## Fréquence de vérification

| Canal | Fréquence | Déclenchement |
|---|---|---|
| `GET /admin/ia/drift-report` | **Hebdomadaire** | Manuel ou cron externe (ex: `0 8 * * MON`) |
| Accuracy check sur `actual_outcome` | Mensuel (fin de mois) | Manuel — nécessite des dossiers clôturés |

---

## Seuils de drift (Evidently DataDriftPreset)

### Niveau 1 — Alerte WARNING (Sentry `warning`)

**Condition :** `drift_score > 0.15` sur **≥ 2 features critiques** simultanément.

Features critiques (features à fort poids SHAP historique) :
- `debt_to_equity`
- `net_margin`
- `current_ratio`
- `operating_cash_flow`
- `z_score_altman`

**Action :**
- Sentry `sentry_sdk.capture_message("IA drift WARNING", level="warning")`
- Notification équipe data science
- Ré-entraînement **non obligatoire** — surveiller la semaine suivante

```python
# Exemple d'intégration dans l'endpoint /admin/ia/drift-report
if report["drift_score"] > 0.15 and len(report["drifted_features"]) >= 2:
    sentry_sdk.capture_message(
        f"IA drift WARNING — {report['drifted_features']}",
        level="warning",
        extras=report
    )
```

---

### Niveau 2 — Alerte ERROR (Sentry `error` + ticket manuel)

**Condition :** `drift_score > 0.30` sur **n'importe quelle feature** (même une seule).

**Action :**
- Sentry `sentry_sdk.capture_message("IA drift CRITICAL", level="error")`
- **Ticket manuel obligatoire** dans l'issue tracker (GitHub Issues ou Jira)
- Suspendre l'affichage du score IA dans les nouveaux rapports jusqu'à investigation
- Investigation root cause : changement de population ? Saisonnalité ? Biais de sélection ?

```python
if report["drift_score"] > 0.30:
    sentry_sdk.capture_message(
        f"IA drift CRITICAL — score {report['drift_score']}",
        level="error",
        extras=report
    )
```

---

### Niveau 3 — Ré-entraînement OBLIGATOIRE

**Condition :** Accuracy sur `actual_outcome` calculée sur **30 jours glissants** < **0.75** (75%).

> `actual_outcome` est rempli manuellement quand le dossier est clôturé (DEFAULT ou NO_DEFAULT).
> L'accuracy mesure si `ia_risk_class` ∈ {HIGH, CRITICAL} coïncide avec DEFAULT, et {LOW, MODERATE} avec NO_DEFAULT.

```sql
-- Requête de vérification mensuelle
SELECT
    COUNT(*) FILTER (WHERE actual_outcome IS NOT NULL) AS total_labeled,
    COUNT(*) FILTER (
        WHERE (ia_risk_class IN ('HIGH', 'CRITICAL') AND actual_outcome = 'DEFAULT')
           OR (ia_risk_class IN ('LOW', 'MODERATE') AND actual_outcome = 'NO_DEFAULT')
    ) AS correct,
    ROUND(
        COUNT(*) FILTER (
            WHERE (ia_risk_class IN ('HIGH', 'CRITICAL') AND actual_outcome = 'DEFAULT')
               OR (ia_risk_class IN ('LOW', 'MODERATE') AND actual_outcome = 'NO_DEFAULT')
        )::numeric / NULLIF(COUNT(*) FILTER (WHERE actual_outcome IS NOT NULL), 0), 4
    ) AS accuracy
FROM ia_predictions
WHERE created_at >= NOW() - INTERVAL '30 days';
```

**Action :**
- Déclencher le pipeline de ré-entraînement hors production (staging data science)
- Valider le nouveau modèle sur holdout set avant déploiement
- Déployer via `PUT /api/v1/ia/models/{id}/activate` (endpoint existant)
- Documenter le ré-entraînement dans CHANGELOG.md

---

## Procédure de ré-entraînement (manuel)

1. **Export des données** depuis `ia_predictions` + `ia_features` pour les N derniers mois
2. **Nettoyage** : filtrer les predicitons sans `actual_outcome`
3. **Re-split** train/val/test avec stratification sur `ia_risk_class`
4. **Entraînement** : LightGBM avec les mêmes hyperparamètres (ou gridsearch si drift > 0.30)
5. **Évaluation** : AUC-ROC ≥ 0.85, F1-macro ≥ 0.70
6. **Déploiement staging** en shadow mode (les deux modèles tournent en parallèle, logs comparés)
7. **Validation humaine** par l'analyste senior sur 50 dossiers récents
8. **Activation production** via l'API admin

---

## Exemple de cron externe (optionnel)

```bash
# /etc/cron.d/finaces-drift-check
# Lance le check drift chaque lundi à 8h UTC
0 8 * * MON root curl --silent --fail \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  https://staging.finaces.io/admin/ia/drift-report >> /var/log/finaces-drift.log 2>&1
```

---

## Historique des ré-entraînements

| Date | Motif | Modèle précédent | Nouveau modèle | AUC-ROC | Validé par |
|---|---|---|---|---|---|
| *(premier déploiement en attente)* | — | — | — | — | — |
