# Préparation de la base commune — 24 octobre 2026

## État actuel et décision

Le propriétaire souhaite une base commune en ligne pour L’Héritage et son bot Discord, avec des sauvegardes automatiques sur son PC. Aucun projet Supabase n’a encore été créé. Ce document prépare la migration ; il ne signifie pas qu’un raccordement distant ou une synchronisation est déjà opérationnel.

Analyse effectuée :

- Le frontend HTML/CSS/JS utilise les API FastAPI existantes ; son design et sa navigation préchargée peuvent être conservés.
- `backend/storage.py` utilise SQLite. Les requêtes de comptes, sessions, permissions et journal sont aussi réparties dans `security.py`, `app.py` et `auditing.py`.
- Les données métier sont dans `domain_store`, sous forme JSON ; les quotas sont dans une autre base SQLite.
- Le bot écrit actuellement dans Google Sheets et plusieurs fichiers JSON. Le site reçoit seulement un instantané manuel de ces sources.
- Le code comporte des opérations propres à SQLite : paramètres `?`, `INSERT OR IGNORE/REPLACE`, fonctions JSON SQLite, transactions et sauvegardes natives. Remplacer uniquement une adresse de connexion ne suffit donc pas pour PostgreSQL.
- Les photos et la clé de chiffrement des jetons sont des fichiers privés distincts de la base. Une sauvegarde SQL seule ne constitue pas une restauration complète de l’application.

Aucun code du bot, donnée réelle, fichier privé ou réglage du serveur actif n’a été modifié pendant cette préparation.

## Architecture proposée

Le navigateur et le bot passent par le même serveur Python pour les opérations métier. Ce serveur vérifie les droits, applique les règles et enregistre la transaction dans PostgreSQL hébergé par Supabase.

```text
Site web ───────────┐
                   ├── Serveur Python de gestion ── PostgreSQL / Supabase
Bot Discord ────────┘                                      │
                                                          └── Sauvegardes vers le PC
```

Cette architecture réutilise les règles métier testées, l’identité Discord, le Conseil des Accès et les logs avant/après. Le navigateur ne reçoit aucun mot de passe de base, secret du bot ou clé privilégiée Supabase. Un membre sans autorisation ne reçoit toujours pas les données de la catégorie concernée.

La connexion Discord existante peut rester gérée par le serveur Python : l’ajout de Supabase pour PostgreSQL n’impose pas de remplacer les comptes par Supabase Auth. Les tables applicatives seront dans un schéma privé, sans exposition directe aux rôles navigateur `anon` et `authenticated` ; les droits SQL et RLS devront être vérifiés sur le projet de test.

Le bot utilisera une liaison serveur authentifiée, avec identifiant d’opération stable contre les doublons. Le serveur continuera de vérifier le membre et ses autorisations. Un événement signé ne doit pas permettre à un navigateur de s’attribuer une identité. Le traitement d’une commande, sa mutation et son log doivent rester atomiques.

Sources techniques : [connexion PostgreSQL](https://supabase.com/docs/guides/database/connecting-to-postgres), [sécurisation de l’API et schémas](https://supabase.com/docs/guides/api/securing-your-api), [responsabilités de sécurité](https://supabase.com/docs/guides/deployment/shared-responsibility-model).

## Ordre de réalisation

1. **Créer un projet de test.** Nom conseillé `heritage-test`, offre gratuite pour les essais, région européenne. Conserver le mot de passe dans un gestionnaire privé ; ne pas le transmettre dans le chat. La création du compte et du projet est à effectuer par le propriétaire.
2. **Préparer la connexion privée.** Récupérer les paramètres depuis le tableau de bord Supabase et les enregistrer dans une configuration séparée de celle de la preview. Choisir le mode de connexion adapté à l’hôte Python ; vérifier TLS et la connectivité sans afficher les secrets. Ne pas utiliser de clé privilégiée dans `static/`.
3. **Adapter le stockage dans un environnement isolé.** Créer le schéma PostgreSQL, adapter les accès SQL, les transactions, les lectures JSON et le journal immuable. Préserver les comptes, identifiants, permissions et archives. Définir aussi le stockage des photos, des quotas et de la clé de chiffrement. La version locale reste disponible pendant les essais.
4. **Répéter une migration sur copie.** Faire une sauvegarde cohérente, importer dans le projet de test, comparer les comptes, permissions, données métier et anciens logs. Vérifier le déchiffrement des jetons avec la bonne clé et la présence des photos. Refuser les données incohérentes avant remplacement. Une migration de test ne doit jamais écraser une base déjà utilisée.
5. **Raccorder le bot de test au moteur commun.** Adapter ses commandes progressivement. Vérifier qu’une opération créée sur une interface est visible sur l’autre, qu’un double envoi ne crée qu’une opération et qu’un lot ne peut pas être récupéré trop tôt. Définir une seule responsabilité pour les resets hebdomadaires. Les classeurs et messages existants ne doivent pas rester une seconde source concurrente qui écrase la base commune.
6. **Mettre en place les sauvegardes PC.** Programmer une tâche locale qui télécharge une sauvegarde cohérente de la base et les fichiers nécessaires. Protéger les fichiers, éviter les noms/secrets en ligne de commande et conserver les erreurs visibles. Tester une restauration dans une destination séparée avant d’activer la planification.
7. **Valider les tests et présenter la bascule.** Rejouer les tests de sécurité, rôles, concurrence, navigation et restauration sur PostgreSQL réel de test. Les tests actuels utilisent SQLite : leurs succès ne prouvent pas encore la compatibilité PostgreSQL. Vérifier également les pannes réseau, reprises et limites de connexions. Présenter le résultat avant toute migration réelle, changement du bot actif ou publication publique.

## Sauvegardes et disponibilité

Les sauvegardes automatiques vers le PC nécessitent que celui-ci soit allumé et connecté. La base en ligne reste la source commune ; un export local ne doit pas être réimporté automatiquement par-dessus les opérations des employés. Une sauvegarde indépendante supplémentaire et la vérification périodique des restaurations restent utiles si le PC est indisponible.

Les sauvegardes gérées par Supabase dépendent de l’offre. La documentation recommande des exports réguliers pour l’offre gratuite. Le contenu des fichiers Storage doit être sauvegardé séparément du SQL si les avatars y sont déplacés. Référence : [sauvegardes Supabase](https://supabase.com/docs/guides/platform/backups).

## Prochaine information nécessaire

Créer le projet de test puis communiquer seulement son nom ou son URL publique, sans mot de passe, chaîne de connexion complète ni clé secrète. Un assistant local privé pourra ensuite servir à saisir la connexion. Aucun accès au compte Supabase du propriétaire n’est disponible dans cette session.

L’hébergement public du frontend et du serveur Python reste à choisir séparément. Un projet Supabase seul ne met pas le serveur Python actuel en ligne. Le choix d’une offre payante et tout déploiement réel nécessitent une décision distincte du propriétaire.
