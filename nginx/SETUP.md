# FinaCES API — Procédure d'installation Nginx sur le VPS (Ubuntu 22.04)

> **Pré-requis** : Le VPS tourne sous Ubuntu 22.04, `docker` et `docker compose` sont déjà installés, et le domaine `staging.finaces.io` pointe sur l'IP du VPS.

---

## Étape 1 — Installer Nginx

```bash
sudo apt update
sudo apt install -y nginx
sudo systemctl enable nginx
sudo systemctl start nginx
```

Vérifie que Nginx répond :
```bash
curl -I http://localhost
# → HTTP/1.1 200 OK (page par défaut Nginx)
```

---

## Étape 2 — Déployer la configuration FinaCES

```bash
# Depuis le répertoire du repo cloné sur le VPS
sudo cp nginx/finaces-api.conf /etc/nginx/sites-available/finaces-api

# Remplacer le domaine placeholder (si pas encore fait dans le fichier)
sudo sed -i 's/staging.adsa.cloud/VOTRE_DOMAINE_REEL/g' /etc/nginx/sites-available/finaces-api

# Activer le site via symlink
sudo ln -sf /etc/nginx/sites-available/finaces-api /etc/nginx/sites-enabled/finaces-api

# Désactiver la config par défaut (optionnel mais recommandé)
sudo rm -f /etc/nginx/sites-enabled/default
```

---

## Étape 3 — Valider et recharger Nginx

```bash
sudo nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

sudo systemctl reload nginx
```

Teste le healthcheck direct :
```bash
curl http://staging.finaces.io/health
# → OK
```

---

## Étape 4 — Lancer le stack applicatif Docker

```bash
cd /opt/finaces/finaces-api

# S'assurer que .env.production est configuré avec les bons secrets
# (copier depuis .env.production.example et remplir les valeurs)

docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
# → db, redis, api doivent être en état "healthy" / "running"
```

Teste l'API via Nginx :
```bash
curl http://staging.finaces.io/api/v1/health
# → {"status": "ok", ...}
```

---

## Étape 5 — Obtenir le certificat Let's Encrypt (HTTPS)

```bash
# Installer Certbot + plugin Nginx
sudo apt install -y certbot python3-certbot-nginx

# Obtenir et installer le certificat
# Certbot modifie automatiquement /etc/nginx/sites-available/finaces-api
# pour ajouter le bloc listen 443 ssl et la redirection HTTP→HTTPS
sudo certbot --nginx -d staging.finaces.io

# Suivre l'assistant interactif :
# - Entrer un email de contact
# - Accepter les CGU
# - Choisir "Redirect" pour la redirection HTTP→HTTPS automatique
```

Après Certbot, vérifie que HTTPS fonctionne :
```bash
curl -I https://staging.finaces.io/health
# → HTTP/2 200
# → strict-transport-security: max-age=...
```

---

## Étape 6 — Vérifier le renouvellement automatique

Certbot installe un timer systemd qui renouvelle automatiquement avant expiration :

```bash
# Tester le renouvellement sans effectuer de changement
sudo certbot renew --dry-run
# → Simulating renewal of an existing certificate...
# → Congratulations, all simulated renewals succeeded.

# Vérifier le timer systemd
systemctl status certbot.timer
# → Active: active (waiting)

# Voir la date du prochain renouvellement
systemctl list-timers certbot*
```

---

## Résumé de l'architecture finale

```
Internet
    │ :443 (HTTPS)
    ▼
Nginx (VPS, port 443/80)
    │ proxy_pass http://127.0.0.1:8000
    ▼
Docker container api (FastAPI/Uvicorn, port 8000)
    │
    ├── db (PostgreSQL, réseau interne finaces-net)
    └── redis (Redis, réseau interne finaces-net)
```

---

## Troubleshooting rapide

| Problème | Commande de diagnostic |
|---|---|
| Nginx refuse de démarrer | `sudo nginx -t && journalctl -u nginx -n 50` |
| Container API ne répond pas | `docker compose -f docker-compose.prod.yml logs api` |
| Certificat expiré | `sudo certbot renew` |
| Port 443 bloqué | `sudo ufw allow 'Nginx Full'` |
| Voir les accès Nginx | `sudo tail -f /var/log/nginx/access.log` |
