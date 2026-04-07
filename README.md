# FinaCES — Backend API

> Moteur d'analyse financière et de scoring IA pour l'évaluation des risques de crédit.

[![CI/CD — FinaCES Backend](https://github.com/adsa/finaces-api/actions/workflows/deploy.yml/badge.svg)](https://github.com/adsa/finaces-api/actions/workflows/deploy.yml)

## 🚀 Stack Technique

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) (Python 3.12)
- **Base de données**: [PostgreSQL](https://www.postgresql.org/) 15 (via SQLAlchemy + AsyncPG)
- **Cache / Task Queue**: [Redis](https://redis.io/)
- **Moteur IA**: [LightGBM](https://lightgbm.readthedocs.io/), [XGBoost](https://xgboost.readthedocs.io/)
- **MLOps**: [Evidently](https://www.evidentlyai.com/) (Drift detection), [Sentry](https://sentry.io/) (Monitoring)
- **Infrastructure**: [Docker](https://www.docker.com/), [Nginx](https://www.nginx.com/), [GitHub Actions](https://github.com/features/actions)

---

## 🛠 Prérequis

- **Python 3.12**+
- **Docker** & **Docker Compose** (pour la DB et Redis en local)
- **PostgreSQL Client** (`psql`)

---

## 💻 Setup Local (Rapide)

```bash
# 1. Cloner le repo
git clone https://github.com/adsa/finaces-api.git && cd finaces-api

# 2. Configurer l'environnement
cp .env.example .env

# 3. Lancer les services d'infrastructure
docker compose up db redis -d

# 4. Installer les dépendances (dans un venv)
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 5. Lancer l'application
uvicorn app.main:app --reload
```

L'API est alors disponible sur : [http://localhost:8000/docs](http://localhost:8000/docs)

---

## ⚙️ Variables d'Environnement

Configurez ces variables dans votre fichier `.env` (local) ou `.env.production` (VPS).

| Variable | Valeur exemple | Statut VPS |
|---|---|---|
| `ENVIRONMENT` | `staging`, `production` | 🟡 `staging` par défaut |
| `SECRET_KEY` | *(min 32 chars)* | 🔴 À définir (Secrets GitHub) |
| `DATABASE_URL` | `postgresql+asyncpg://...` | 🔴 À définir (Secrets GitHub) |
| `POSTGRES_PASSWORD` | `...` | 🔴 À définir (Secrets GitHub) |
| `REDIS_URL` | `redis://redis:6379/0` | 🟡 OK (interne Docker) |
| `SENTRY_DSN` | `https://...@sentry.io/...` | 🟡 Optionnel |
| `POSTGRES_USER` | `finaces` | 🟡 OK |
| `POSTGRES_DB` | `finaces` | 🟡 OK |

---

## 📖 Commandes Utiles

### Tests & Qualité
```bash
# Lancer la suite de tests avec couverture
pytest tests/ --cov=app

# Lancer un smoke test sur l'URL de staging
curl --fail https://staging.adsa.cloud/health
```

### Base de données (Alembic)
```bash
# Appliquer les migrations
alembic upgrade head

# Créer une nouvelle migration
alembic revision --autogenerate -m "description"
```

### MLOps
```bash
# Générer un rapport de drift (Admin uniquement)
curl -H "Authorization: Bearer $TOKEN" https://staging.adsa.cloud/admin/ia/drift-report
```

---

## 📁 Architecture des dossiers

```text
finaces-api/
├── alembic/            # Migrations de base de données
├── app/
│   ├── api/            # Routes FastAPI (v1, admin)
│   ├── core/           # Configuration, Sécurité, Logging
│   ├── db/             # Modèles ORM et session
│   ├── engines/        # Logique métier (IA, Scoring, Ratios)
│   ├── schemas/        # Modèles Pydantic (In/Out)
│   └── services/       # Orchestration et services externes
├── docs/               # Documentation détaillée (API.md)
├── ml/                 # Pipelines d'entraînement et modèles
├── nginx/              # Configuration Reverse Proxy et SETUP.md
└── tests/              # Suite de tests (Unit, Integration, E2E)
```

---

## 🌍 Déploiement

Le déploiement est automatisé via **GitHub Actions** sur chaque push sur `main`.
- **IP VPS** : `168.231.84.70`
- **Domaine** : `staging.adsa.cloud`
- **Procédure d'infra** : Voir [nginx/SETUP.md](nginx/SETUP.md)
