# Essais du site

Le site public enregistre les essais dans le stockage local du navigateur.
Les données restent après un rechargement, sur le même navigateur et la même
adresse. Elles ne sont pas partagées entre appareils et ne sont pas envoyées au
bot Discord. Effacer les données du site dans le navigateur efface ces essais.

## Vérifier une fiche de véhicules

1. Entrer dans le domaine et ouvrir « Véhicule tombola ».
2. Préparer une fiche : renseigner au moins deux modèles. Les prix sont facultatifs.
3. Enregistrer la fiche. Elle doit apparaître dans la semaine choisie.
4. Essayer « À acheter », le paiement et « Modifier véhicules / prix ».
5. Recharger la page : les modèles, prix et états doivent rester présents.
6. Ouvrir l’historique ou le journal pour retrouver les opérations locales.

Les dossiers et les lots de machines sont également enregistrables. Un seul lot
peut être actif ; sa récupération reste bloquée pendant le cycle de 4 h 45.

## Tests automatisés

Avec Node.js installé, depuis la racine du projet :

```powershell
node tests/local_business.mjs
node tests/browser_pages.mjs
```

Le premier teste les opérations, la persistance, les entrées invalides et un
stockage saturé. Le second utilise Chrome avec un profil temporaire et vérifie
les formulaires réels, la sauvegarde après rechargement, les panneaux d’accès,
la navigation, les erreurs de chargement et l’affichage mobile. Les données
personnelles du navigateur ne sont pas utilisées.

Les vrais comptes, rôles et sessions Discord nécessitent toujours le serveur Python.
