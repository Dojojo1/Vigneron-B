# État de sécurité et de fiabilité — 24 octobre 2026

> Document historique : depuis le 25 octobre 2026, la dernière version est uniquement dans `site/`. Démarrage : `./lancer-site.sh` depuis la racine du projet. Les anciens noms de dossiers ci-dessous décrivent la situation au moment du contrôle.

Périmètre : prévisualisation `preview-discord/`. Relecture ciblée du code, tests automatiques et vérifications métier dans une base temporaire. Aucun changement du bot ou des données métier réelles pendant ce contrôle. Ce document n’est pas un audit de pénétration exhaustif.

## État actuel

Le mode local sans Discord est activé. Le lancement prévu écoute uniquement sur `127.0.0.1:8081`. Ce mode refuse les clients distants, les noms d’hôte publics et les en-têtes usuels de proxy/tunnel. Il donne des droits étendus à un profil de test distinct des utilisateurs Discord ; il doit rester réservé aux essais sur cette machine. Il ne doit pas être utilisé derrière un proxy qui masquerait l’origine des connexions.

Le site n’est pas encore prêt pour une utilisation publique avec les données réelles.

## Protections présentes

- OAuth2 avec état aléatoire à usage unique et cookie de retour ; code conservé pendant le mode local.
- Sessions côté serveur, cookie HttpOnly/SameSite et Secure lorsque l’adresse HTTPS est configurée.
- Vérification serveur des pages et API ; refus par défaut des nouvelles pages privées.
- En mode Discord : appartenance au serveur, rôle Employé requis sauf exception du propriétaire, rôle prioritaire unique et révocation après vérification du cache.
- CSRF et origine contrôlés pour les écritures authentifiées.
- Jetons OAuth chiffrés ; secrets non renvoyés au navigateur ; fichiers privés `.env`, base et clé avec permissions `0600`.
- Validation et réencodage des photos, limite de taille des requêtes et protections HTTP.
- Machines : récupération refusée avant la fin du cycle, récupération explicite requise avant le lancement suivant, vérification transactionnelle contre deux lancements simultanés, récupération répétée sans double crédit. Les corrections d’heure restent distinctes et le contrôle utilise l’heure enregistrée ; la restriction des corrections aux auteurs reste à terminer ci-dessous.
- Journal permanent : changements avant/après, acteurs et corrélation des requêtes ; filtres, pagination et détails à la demande ; refus, erreurs, consultations, imports et exports ; aucune purge automatique et triggers interdisant la modification/suppression. Les nouvelles mutations et leur journal sont atomiques.
- Écritures métier dans des transactions SQLite ; sauvegardes avant import du bot et réinitialisation des données de test ; détection d’une modification concurrente pendant un import.

## Points vérifiés à corriger avant usage réel

1. **Correction des opérations d’autrui.** Un membre disposant de la page Machines peut actuellement envoyer une correction d’heure sur un lot tiers. Une restriction « chacun corrige ses propres opérations » n’a pas été activée pendant cet audit ; son application reste distincte de l’accès à la page. La récupération d’un lot tiers par un employé autorisé reste permise comme demandé.
2. **Sauvegardes et restauration.** Un essai complet de restauration locale est maintenant réussi et reproductible via `scripts/verify_restore.py` : base, clé, configuration, avatars, intégrité et pages. Les sauvegardes ponctuelles existantes ne constituent pas une stratégie automatique hors machine ; destination et programmation restent à configurer.
3. **Déploiement et abus.** Réactiver OAuth2 avant toute exposition publique ; configurer HTTPS, proxy de confiance, service de démarrage et surveillance. Des limites persistantes par IP et des plafonds Discord/Google sont maintenant présents dans la preview (voir README). Le serveur local ignore les en-têtes proxy ; la configuration de confiance et une protection réseau en amont restent à préparer avant exposition publique.
4. **Synchronisation métier.** L’import actuel reste une copie en lecture des sources du bot. La liaison dans les deux sens, les reprises après panne, la gestion des doublons et le recalcul des archives après correction restent à développer et à tester.

## Vérifications effectuées

- `preview-discord/.venv/bin/python -m pytest -q` : **237 tests réussis** au total après la vérification complète du 24 octobre : autorisations, OAuth simulé, entrées invalides, payloads externes, révocations concurrentes, plafonds partagés, métier/imports/archives, lectures ciblées, index, déduplication, cycle machines, journal durable et restauration.
- Révocation concurrente : trois courses reproduites et testées, puis corrigées par sérialisation du connecteur avec les vérifications dans le worker unique. Une configuration future à plusieurs workers nécessitera une invalidation coordonnée.
- Corps fragmentés bornés en mémoire, soumissions du journal préservées même pendant l’attente d’une place, validation stricte des réponses Discord et refus propre des requêtes JSON/paramètres de sécurité invalides.
- Navigation : un GET autorisé, réponse conditionnelle 304 liée au compte et au rôle, cache mémoire borné affiché uniquement après vérification serveur, refus fermés et invalidation après écriture. Onze nouveaux tests couvrent versions, identités, révocations, Conseil et métadonnées de session ; un scénario Firefox isolé vérifie l’absence de restitution du cache avant autorisation et le nombre d’appels.
- Performances sans perte de durabilité : réservations de quotas visiteurs déjà débitées sur disque (9 nouveaux tests), requêtes SQLite hors boucle HTTP et transactions de révocation intactes (6 nouveaux tests), regroupement durable des logs HTTP avec attente avant réponse, contexte de chaque requête, annulation du visiteur et rollback de lot (4 nouveaux tests). Les plafonds fournisseurs restent exacts. Aucun changement des secrets, droits ou réglages SQLite de durabilité.
- Vérification Firefox du journal : valeurs avant/après, échappement des textes, détails chargés à la demande, filtres vides, pagination, reprise d’un signalement réseau, lien depuis le Conseil et affichage mobile.
- Vérifications Firefox sur une base temporaire : chargements visibles, annulation d’une navigation remplacée, conservation des champs, double soumission, données à la demande, pagination, écrans vides et reprise après erreurs réseau/serveur/délai.
- Les vérifications initiales de récupération précoce et de lancement forcé sont maintenant remplacées par des tests qui exigent leur refus. Le constat de correction des opérations d’autrui reste à traiter. Ces contrôles utilisent des données temporaires, sans appel au vrai Discord ni écriture dans la base du site.
- Vérification des paramètres actifs sans affichage de secrets : mode local activé, HTTPS non configuré pour cette adresse locale, permissions `0600` pour les trois fichiers privés contrôlés.

## Limites du contrôle

Les tests existants ne prouvent pas l’absence de failles. Pas de test d’intrusion externe, de vérification exhaustive des dépendances vulnérables ou de test de charge prolongé. La restauration locale est contrôlée ; une restauration après perte totale du PC depuis une sauvegarde distante reste à tester. Ne pas annoncer une absence de failles ou une préparation à la production sur cette seule base.

Références de contrôle : [OWASP — autorisations](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html) et [OWASP — journalisation](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html).

Les valeurs avant/après des anciens événements ne sont pas récupérables rétroactivement. Le journal n’efface aucun ancien événement, mais ne reconstitue pas des informations qui n’avaient jamais été enregistrées. Les erreurs navigateur ne sont confirmées dans le journal qu’après réception par le serveur ; voir les limites et la file locale dans le README.

Voir [le bilan complet](AUDIT-COMPLET-2026-10-24.md) pour les corrections, les parcours de toutes les pages en largeur 390 px, la reprise après limite d’utilisation et les points restant à préparer. La dernière activation a conservé comptes, permissions, sessions, données métier et les 599 anciens logs contrôlés.
