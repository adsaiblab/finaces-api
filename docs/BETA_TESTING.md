# Critères de Beta Testing — FinaCES

Ce document définit le cadre, les scénarios et les critères de sortie de la phase de Beta Testing sur l'environnement de staging.

## 👥 Profil des Testeurs

- **Cible** : Analystes crédit, chargés d'affaires (Secteur Bancaire / Financement).
- **Volume** : 3 à 5 testeurs maximum pour cette phase.
- **Accès** : Comptes créés manuellement par l'administrateur (Pas d'auto-enregistrement).

## ✅ Scénarios de Test Obligatoires (Happy Path)

Pour valider le cycle de vie complet du produit, chaque testeur doit effectuer :

1. **Cycle de Vie Dossier** : Créer un dossier complet → Saisir les données financières → Calculer le scoring MCC → Lancer la prédiction IA → Générer le rapport final.
2. **Export PDF** : Télécharger et vérifier la mise en page du rapport PDF d'un dossier finalisé.
3. **Export Word** : Télécharger et vérifier le contenu éditable du rapport Word d'un dossier finalisé.
4. **Monitoring Dashboard** : Consulter la liste des dossiers, tester les filtres par statut et la recherche par référence.
5. **Gestion de Session** : Se connecter, se déconnecter et vérifier le fonctionnement après une période d'inactivité (refresh token).

## ⚠️ Scénarios Limites (Edge Cases)

Ces cas doivent être testés pour garantir la robustesse du système :

- **Données Manquantes** : Tenter de soumettre un dossier incomplet → Vérifier que le message d'erreur est clair et non technique.
- **Expiration de Session** : Laisser l'onglet ouvert sans activité → Vérifier la redirection propre vers le login (sans crash).
- **Export Prématuré** : Tenter d'exporter un rapport sur un dossier non finalisé → Vérifier que l'UI l'empêche ou affiche une erreur explicite.
- **Isolation Sécurité** : Tenter d'accéder à l'ID d'un dossier créé par un autre testeur via l'URL → Vérifier que le serveur renvoie une **403 Forbidden**.

## 🏁 Critères de Sortie (Definition of Done)

La version sera considérée comme prête pour la transition suite à :

- **Zéro bug bloquant** (inutilisabilité d'un des 5 happy paths).
- **Maximum 3 bugs mineurs** ouverts (cosmétique, UX non bloquant).
- **Performance** : 95% des générations de rapports calculées en **moins de 10 secondes**.
- **Isolation Multi-tenant** : Validation stricte de l'étanchéité des données entre testeurs.
- **Infrastructure** : Smoke test CI vert sur `https://staging.adsa.cloud/health`.

## 📈 Collecte de Feedback

- **Saisie des Bugs** : Créer une Issue sur le repo GitHub avec le label `beta-feedback`.
- **Formulaire de Feedback** : Questionnaire Google Form / Notion transmis en fin de phase.
- **Débriefing** : Séance de 30 minutes prévue 1 semaine après le début des tests.

---

## 🚦 Critères Go/No-Go Production

Le passage en production (v1.0) est conditionné par le respect strict des indicateurs suivants :

- [ ] ✅ **0 bug CRITICAL** (Sévérité 🔴)
- [ ] ✅ **0 bug Bloquant** sur le flux principal Blocs 1→10 (Sévérité 🟠)
- [ ] ✅ **123/123 tests E2E Playwright** verts sur l'environnement beta
