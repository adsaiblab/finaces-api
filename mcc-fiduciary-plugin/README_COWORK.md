# MCC Fiduciary Plugin — Guide d'Installation et d'Utilisation

**Version :** 2.0.0
**Compatibilité :** Claude Code CLI ≥ 1.0, Claude Desktop (Cowork mode)
**Serveur MCP :** FEW Solo V2.0 (FastMCP / Python 3.11+)

---

## 1. Prérequis

Avant d'installer le plugin, assurez-vous d'avoir :

- **Python 3.11+** avec pip
- **Dépendances FEW Solo** installées (`pip install -r requirements.txt`)
- **Base de données** initialisée (SQLite en local ou PostgreSQL en production)
- **Claude Code CLI** installé (`npm install -g @anthropic-ai/claude-code`) ou **Claude Desktop** avec Cowork mode activé

---

## 2. Installation Locale (Mode Développement)

### 2.1 — Via Claude Code CLI (recommandé)

La méthode la plus simple pour charger le plugin en local :

```bash
# Depuis la racine du projet few_solo/
claude --plugin-dir ./mcc-fiduciary-plugin
```

Cette commande lance Claude Code avec le plugin chargé localement. Le serveur MCP sera démarré automatiquement via stdio grâce au `.mcp.json`.

### 2.2 — Installation Persistante (Claude Code Settings)

Pour que le plugin soit disponible à chaque session sans le flag `--plugin-dir` :

```bash
# Installer le plugin dans le répertoire global
claude plugin install ./mcc-fiduciary-plugin
```

Pour le désinstaller :
```bash
claude plugin uninstall mcc-fiduciary-plugin
```

### 2.3 — Configuration Claude Desktop (Cowork Mode)

Pour utiliser le plugin dans Claude Desktop avec le mode Cowork, ajoutez la configuration MCP dans le fichier de settings Claude Desktop.

**Emplacement du fichier de configuration :**
- macOS : `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows : `%APPDATA%\Claude\claude_desktop_config.json`
- Linux : `~/.config/claude/claude_desktop_config.json`

**Configuration à ajouter :**

```json
{
  "mcpServers": {
    "mcc_fiduciary_server": {
      "command": "python",
      "args": ["/chemin/absolu/vers/few_solo/mcp_server.py"],
      "env": {
        "DATABASE_URL": "sqlite:////chemin/absolu/vers/few_solo/data/few_solo.db",
        "PYTHONPATH": "/chemin/absolu/vers/few_solo"
      }
    }
  }
}
```

Remplacez `/chemin/absolu/vers/few_solo/` par le chemin réel de votre installation.

**Vérification :** Relancez Claude Desktop. Le serveur MCP doit apparaître dans la liste des outils disponibles. Testez avec :
```
/mcc-fiduciary-plugin:evaluer <case_id> <valeur_contrat> <durée_mois>
```

---

## 3. Utilisation

### 3.1 — Commande Principale : `/evaluer`

```
/mcc-fiduciary-plugin:evaluer <case_id> <valeur_contrat> <durée_mois>
```

**Exemple :**
```
/mcc-fiduciary-plugin:evaluer case-s1 5000000 24
```

Cette commande déclenche la skill `analyze-bidder` qui :
1. Collecte les données du dossier via les outils MCP READ
2. Exécute la pipeline complète (normalisation → ratios → stress → scoring)
3. Produit l'interprétation experte des 5 piliers
4. Rédige les sections narratives du rapport MCC-grade
5. Délivre un résumé exécutif avec score, classification et recommandation

### 3.2 — Outils MCP Disponibles

Le serveur expose 11 outils accessibles directement :

| Outil | Type | Description |
|-------|------|-------------|
| `read_case_summary` | READ | Contexte du dossier (bidder, contrat, type) |
| `read_gate_status` | READ | Verdict du gate documentaire |
| `read_financial_ratios` | READ | 25+ ratios par exercice fiscal |
| `read_trends_analysis` | READ | CAGR, pentes, cross-pillar patterns |
| `read_stress_results` | READ | Scénarios de stress test |
| `read_scorecard` | READ | Score final et classification |
| `read_consortium_data` | READ | Données consortium (si applicable) |
| `read_report_sections` | READ | Sections du rapport pré-généré |
| `trigger_full_evaluation` | WRITE | Déclenche la pipeline complète |
| `write_interpretation` | WRITE | Persiste l'interprétation experte |
| `write_report_narrative` | WRITE | Enrichit les sections narratives |

### 3.3 — Workflow Typique

1. **Créer un dossier** via l'API REST (`POST /api/cases/`)
2. **Saisir les états financiers** via l'interface React ou l'API
3. **Enregistrer les documents** dans le gate documentaire
4. **Lancer l'évaluation** : `/mcc-fiduciary-plugin:evaluer <case_id> <montant> <mois>`
5. **Récupérer le rapport** : le rapport MCC-grade est généré automatiquement

---

## 4. Mise à Jour du Plugin

### 4.1 — Mise à jour des fichiers

```bash
# Depuis few_solo/
git pull origin main

# Si installé via plugin install, réinstaller :
claude plugin uninstall mcc-fiduciary-plugin
claude plugin install ./mcc-fiduciary-plugin
```

### 4.2 — Vider le Cache Cowork

Si le plugin ne se met pas à jour après modification :

```bash
# macOS
rm -rf ~/Library/Caches/claude-desktop/plugins/mcc-fiduciary-plugin/

# Linux
rm -rf ~/.cache/claude-desktop/plugins/mcc-fiduciary-plugin/

# Windows (PowerShell)
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\claude-desktop\plugins\mcc-fiduciary-plugin\"
```

Puis relancez Claude Desktop.

### 4.3 — Mise à Jour de la Base de Données

Si le schéma DB a changé :

```bash
cd few_solo/
alembic upgrade head
```

---

## 5. Déploiement VPS (Production)

### 5.1 — Architecture de Déploiement

```
┌─────────────────────────────┐
│   Claude Desktop / Cowork   │
│   (poste analyste)          │
│                             │
│   Plugin .mcp.json          │
│   transport: "sse"          │
│   url: https://vps.xx/sse   │
│   headers: {API-Key: ...}   │
└──────────┬──────────────────┘
           │ HTTPS (SSE)
           ▼
┌──────────────────────────────┐
│   VPS / Cloud Server         │
│                              │
│   ┌────────────────────────┐ │
│   │  Nginx (reverse proxy) │ │
│   │  SSL/TLS termination   │ │
│   │  API Key validation    │ │
│   └──────────┬─────────────┘ │
│              │               │
│   ┌──────────▼─────────────┐ │
│   │  MCP Server (FastMCP)  │ │
│   │  Port 8080 (interne)   │ │
│   │  Transport: SSE        │ │
│   └──────────┬─────────────┘ │
│              │               │
│   ┌──────────▼─────────────┐ │
│   │  PostgreSQL            │ │
│   │  Port 5432             │ │
│   └────────────────────────┘ │
│                              │
│   ┌────────────────────────┐ │
│   │  FastAPI (optionnel)   │ │
│   │  Port 8000             │ │
│   └────────────────────────┘ │
└──────────────────────────────┘
```

### 5.2 — Reconfiguration .mcp.json pour VPS

Lorsque le serveur MCP est déployé sur un VPS, le `.mcp.json` du plugin doit être reconfiguré pour utiliser le transport SSE via HTTPS :

**Fichier :** `mcc-fiduciary-plugin/.mcp.json` (version VPS)

```json
{
  "mcpServers": {
    "mcc_fiduciary_server": {
      "url": "https://votre-vps.example.com/sse",
      "transport": "sse",
      "headers": {
        "X-API-Key": "${MCC_API_KEY}"
      }
    }
  }
}
```

**Variables d'environnement côté client :**
```bash
export MCC_API_KEY="votre-clé-api-secrète"
```

### 5.3 — Configuration Nginx (Côté VPS)

```nginx
server {
    listen 443 ssl http2;
    server_name votre-vps.example.com;

    ssl_certificate     /etc/letsencrypt/live/votre-vps.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/votre-vps.example.com/privkey.pem;

    # Validation API Key
    location /sse {
        # Vérification de la clé API
        if ($http_x_api_key != "votre-clé-api-secrète") {
            return 403;
        }

        # Proxy vers le serveur MCP
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # SSE-specific settings
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;
        chunked_transfer_encoding on;
    }
}
```

### 5.4 — Docker Compose (Côté VPS)

```yaml
version: "3.9"
services:
  few-mcp:
    build:
      context: .
      dockerfile: Dockerfile.mcp
    ports:
      - "8080:8080"
    environment:
      - DATABASE_URL=postgresql://few_admin:${POSTGRES_PASSWORD}@few-db:5432/few_solo_db
      - PYTHONPATH=/app
      - MCP_TRANSPORT=sse
      - MCP_PORT=8080
    depends_on:
      - few-db
    restart: unless-stopped

  few-db:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=few_admin
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=few_solo_db
    volumes:
      - pgdata:/var/lib/postgresql/data
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf
      - /etc/letsencrypt:/etc/letsencrypt:ro
    depends_on:
      - few-mcp
    restart: unless-stopped

volumes:
  pgdata:
```

### 5.5 — Authentification API Key

Le mécanisme d'authentification entre le plugin Cowork (client) et le VPS (serveur) repose sur un header HTTP `X-API-Key` :

1. **Génération de la clé :**
   ```bash
   openssl rand -hex 32
   # Exemple : a3f8b2c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1
   ```

2. **Côté VPS :** Configurer la clé dans le `.env` Docker et dans Nginx (voir ci-dessus)

3. **Côté Client (plugin) :** Configurer la variable d'environnement `MCC_API_KEY` sur le poste de l'analyste

4. **Rotation :** Changez la clé tous les 90 jours. Mettez à jour simultanément le VPS et tous les postes clients.

### 5.6 — Checklist Pré-Déploiement VPS

- [ ] PostgreSQL initialisé avec `alembic upgrade head`
- [ ] Seed data chargé si nécessaire (`python scripts/seed_demo_data.py`)
- [ ] Certificat SSL valide (Let's Encrypt ou certificat d'entreprise)
- [ ] Clé API générée et distribuée aux analystes autorisés
- [ ] `.mcp.json` du plugin reconfiguré en mode SSE/HTTPS
- [ ] Test de connectivité : `curl -H "X-API-Key: ..." https://votre-vps.example.com/sse`
- [ ] Pare-feu : seul le port 443 est ouvert au public
- [ ] Backup automatique PostgreSQL configuré (pg_dump quotidien)

---

## 6. Dépannage

| Problème | Cause probable | Solution |
|----------|----------------|----------|
| `MCP server not found` | Plugin pas chargé | Vérifier `claude --plugin-dir` ou la config Desktop |
| `Connection refused` | Serveur MCP pas démarré | Vérifier que `mcp_server.py` est accessible et que Python est dans le PATH |
| `database is locked` | SQLite en accès concurrent | Passer à PostgreSQL ou utiliser un seul processus |
| `ModuleNotFoundError` | PYTHONPATH manquant | Vérifier la variable `PYTHONPATH` dans `.mcp.json` ou l'env |
| `scoring: FAILED` | Interprétation manquante | Appeler `write_interpretation` avant `trigger_full_evaluation` |
| Plugin obsolète après git pull | Cache plugin | Vider le cache (voir section 4.2) et relancer |
| SSE timeout sur VPS | Nginx buffering | Vérifier `proxy_buffering off` dans la config Nginx |

---

## 7. Structure des Fichiers du Plugin

```
mcc-fiduciary-plugin/
├── .claude-plugin/
│   └── plugin.json              # Manifeste du plugin (nom, version, pointeurs)
├── .mcp.json                    # Configuration du serveur MCP (stdio local / SSE VPS)
├── hooks/
│   └── hooks.json               # Hooks de validation pre/post tool use
├── commands/
│   └── evaluer.md               # Commande slash /evaluer
├── skills/
│   └── analyze-bidder/
│       ├── SKILL.md             # Prompt expert MCC-grade (V2 Claude-Optimized)
│       ├── assets/
│       │   └── Modele-Note.md   # Template de la Note d'Analyse
│       └── references/
│           ├── Interpretation.md   # Guide d'interprétation des ratios
│           └── MCC-Thresholds.md   # Seuils sectoriels MCC
└── README_COWORK.md             # Ce fichier
```

---

**FIN DU README**
