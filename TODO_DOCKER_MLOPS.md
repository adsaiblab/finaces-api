# MLOps Production Requirements (Phase Docker)

Les librairies de monitoring et gouvernance (`mlflow`, `evidently`, `great-expectations`) ont été désactivées dans l'environnement de développement local (macOS ARM64) pour éviter les conflits de compilation avec `pyarrow`.
**ACTION REQUISE POUR LA PROD :** Lors de la création du `Dockerfile` (architecture Linux `amd64`), ces packages devront être obligatoirement réactivés et installés via le `requirements_ia.txt` pour garantir la conformité MCC (Bloc 7).

## Tests Asynchrones & Dette Technique (Pytest)

Actuellement, 6 tests d'intégration API sont marqués en échec attendu (`xfail`). Cela est dû à une limitation connue de la librairie `pytest-asyncio 0.23.x` concernant le partage de l'Event Loop entre le client ASGI (httpx) et le pool de connexion `asyncpg`.

**ACTION REQUISE LORS DE LA DOCKERISATION :**

> 1. Mettre à jour la dépendance vers `pytest-asyncio >= 0.24.0` dans l'environnement Docker.
> 2. Retirer les marqueurs `@pytest.mark.xfail` dans les scripts de tests.
> 3. S'assurer que la suite de tests passe à 100% au vert sans erreur de "Future attached to a different loop".

## Phase de Dockerisation & MLOps (Bloc 8)

Ces éléments doivent être considérés comme prioritaires lors du passage à l'infrastructure de production :

### 1. Le Pipeline CI/CD (L'Usine Automatisée)

C'est ici qu'on s'assure que le code ne "casse" jamais la logique métier.

- **Isolation des Tests** : Utiliser `pytest-asyncio` pour tester toutes les nouvelles routes asynchrones sans bloquer la boucle d'événements.
- **Conteneur d'Entraînement** : Créer un conteneur éphémère qui exécute `training_pipeline.py` uniquement si les tests unitaires passent.
- **Modèle Registry** : Stocker les fichiers `.joblib` (le modèle XGBoost) avec un tag de version et les métriques de performance associées ($F\text{-}beta$ et $Recall$).

### 2. La Surveillance en Production (Le Radar)

C'est le tableau de bord qui clignote si l'IA commence à raconter n'importe quoi.

- **Taux de Divergence** : Monitorer le ratio de dossiers où le Rail 1 (MCC) et le Rail 2 (IA) sont en `MAJOR_DIVERGENCE`. Si ce taux dépasse 15%, une alerte est envoyée.
- **Dérive des Features (Feature Drift)** : Surveiller si la distribution des données entrantes (ex: le `current_ratio` moyen des dossiers) change radicalement par rapport aux données d'entraînement.
- **Latence MCP** : Temps de réponse entre Claude et le serveur `mcp_server.py`.

### 3. Règles de Retrain / Rollback (Le Bouclier)

C'est le protocole de secours.

- **Seuil de Déclenchement** : Ré-entraînement automatique si le $Recall$ tombe sous 0.90 sur les nouvelles données validées.
- **Shadow Deployment** : Avant de remplacer l'ancien modèle par le nouveau, faire tourner le nouveau en "mode fantôme" (il prédit dans les logs mais ne transmet pas le score à Claude) pendant 10 dossiers pour comparer.
- **Rollback Instantané** : Capacité de ré-instancier l'image Docker précédente en moins de 30 secondes si le nouveau modèle génère trop de tensions.
