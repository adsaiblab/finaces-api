# FinaCES — API Reference v1.2

Cette documentation détaille les points d'entrée de l'API FinaCES.
L'URL de base pour le staging est : `https://staging.adsa.cloud/api/v1`

---

## 🔐 Authentification (Auth)

| Méthode | URL | Auth | Description |
|---|---|---|---|
| `GET` | `/auth/csrf-token` | Non | Initialise le cookie XSRF-TOKEN (bootstrap). |
| `POST` | `/auth/login` | Non | Échange credentials contre un JWT (Bearer). |

---

## 📂 Dossiers d'Évaluation (Cases)

| Méthode | URL | Auth | Description |
|---|---|---|---|
| `GET` | `/cases` | Oui | Liste des dossiers avec filtres `status` et `search`. |
| `POST` | `/cases` | Oui | Création d'un dossier (SINGLE ou CONSORTIUM). |
| `GET` | `/cases/{id}` | Oui | Détails complets d'un dossier. |
| `GET` | `/cases/{id}/status` | Oui | Récupère uniquement le statut actuel. |
| `PATCH` | `/cases/{id}/status` | Oui | Transition d'état (State Machine). |
| `POST` | `/cases/{id}/recommendation` | Admin | Définit la recommandation fiduciaire finale. |
| `PATCH` | `/cases/{id}/conclusion` | Admin | Enregistre la conclusion du comité. |
| `GET` | `/cases/bidders` | Oui | Liste de tous les soumissionnaires enregistrés. |

---

## 📝 Rapport & Scoring MCC (Report)

| Méthode | URL | Auth | Description |
|---|---|---|---|
| `POST` | `/cases/{id}/report/build` | Oui | Génère le rapport complet (14 sections). |
| `GET` | `/cases/{id}/report` | Oui | Récupère le dernier rapport généré. |
| `PUT` | `/cases/{id}/report/{rid}/section` | Oui | Mise à jour manuelle d'une section. |
| `POST` | `/cases/{id}/report/{rid}/finalize`| Oui | Marque le rapport comme FINAL (gelé). |

---

## 📥 Exports (Word / PDF)

| Méthode | URL | Auth | Description |
|---|---|---|---|
| `POST` | `/cases/{id}/export/word` | Oui | Déclenche la génération du .docx. |
| `POST` | `/cases/{id}/export/pdf` | Oui | Déclenche la génération du .pdf (WeasyPrint). |
| `GET` | `/cases/{id}/export/word/download` | Oui | Téléchargement du fichier Word généré. |
| `GET` | `/cases/{id}/export/pdf/download` | Oui | Téléchargement du fichier PDF généré. |

---

## 🤖 Intelligence Artificielle (IA)

| Méthode | URL | Auth | Description |
|---|---|---|---|
| `POST` | `/ia/features/{id}` | Oui | Calcul des 40+ features financières. |
| `POST` | `/ia/predict/{id}` | Oui | Inférence ML (Score & Risk Class). |
| `GET` | `/ia/predict/{id}` | Oui | Récupère la dernière prédiction stockée. |
| `POST` | `/ia/dual-scoring/{id}` | Oui | Scoring complet IA + MCC + Analyse de tension. |

---

## 🕵️ Traçabilité (Audit)

| Méthode | URL | Auth | Description |
|---|---|---|---|
| `GET` | `/audit/events` | Oui | Liste filtrée des événements récents. |
| `GET` | `/audit/stats` | Oui | Statistiques agrégées par type d'événement. |
| `GET` | `/audit/trail` | Oui | Piste d'audit complète avec pagination. |
| `GET` | `/audit/export/csv` | Oui | Export complet de la piste au format CSV. |

---

## 🛠 Administration & Système

| Méthode | URL | Auth | Description |
|---|---|---|---|
| `GET` | `/admin/ia/drift-report` | Admin | Génère le rapport de dérive (Evidently). |
| `GET` | `/system/db` | Oui | Métriques de stockage et version PostgreSQL. |
| `GET` | `/system/engines` | Oui | État de santé des moteurs de calcul. |
| `GET` | `/health` | Non | Healthcheck infra (Nginx/Uvicorn). |
