# L’Héritage — décisions fonctionnelles

Décisions confirmées avec le propriétaire le 23 octobre 2026.
Ce document décrit le fonctionnement cible. Il ne signifie pas que la synchronisation bidirectionnelle, les corrections et le journal complet sont déjà développés ou déployés.

## Site et Discord

- Les employés pourront enregistrer leurs opérations sur le site et sur Discord.
- Les deux interfaces devront partager les mêmes données, sans duplication des opérations.
- L’import manuel actuel reste une copie destinée aux essais ; les modifications du site ne sont pas encore transmises au bot ou à Google Sheets.

### Base commune en ligne — choix confirmé le 24 octobre 2026

- Préparer une base commune hébergée en ligne pour le site et le bot, avec Supabase comme solution envisagée.
- Prévoir des sauvegardes automatiques supplémentaires vers le PC ; le PC doit être allumé et connecté pour les recevoir.
- Ne pas remplacer périodiquement toute la base en ligne par un export du PC : les opérations faites sur le site doivent être conservées.
- Le propriétaire n’a pas encore de projet Supabase. Commencer par un projet de test séparé ; aucune base distante, migration ou sauvegarde planifiée n’est actuellement configurée.
- Conserver le design, le système Discord, les permissions et le journal existants. L’hébergement du serveur Python et le raccordement métier du bot constituent des étapes distinctes.
- L’analyse et l’ordre de migration sont détaillés dans [SUPABASE-PREPARATION.md](SUPABASE-PREPARATION.md). La validation de la version de test précède la bascule réelle.

## Autorisations

- Le propriétaire décide des accès depuis le Conseil des Accès, y compris pour les statistiques.
- Ne pas ajouter une restriction fixe « statistiques personnelles seulement » qui remplacerait sa configuration des pages.
- Conserver la règle du rôle Discord prioritaire et l’identité unique de l’Administrateur Suprême définies dans le cahier des charges.
- La désactivation temporaire de Discord concerne uniquement la prévisualisation locale ; elle ne vaut pas autorisation de publier un accès anonyme.

## Lots et corrections

Précision confirmée le 24 octobre 2026 : un seul lot de 5 machines à la fois. Attendre la fin du compteur puis enregistrer la récupération ; aucun nouveau lancement tant que le lot précédent n’est pas récupéré. Aucun lancement ne doit récupérer implicitement le précédent.

- Un employé autorisé peut récupérer un lot lancé par un autre employé.
- Conserver séparément le lanceur et le récupérateur, ainsi que leurs dates d’action.
- Un employé peut corriger ses propres opérations à tout moment, avec un historique.
- Une correction concernant une semaine archivée met à jour cette ancienne semaine : chiffres, totaux et classements concernés sont recalculés.
- Cette correction ne constitue pas un nouveau lancement ni un ajustement dans la semaine actuelle.
- Conserver l’état avant correction, l’état après correction, l’auteur et la date. Une correction ne doit pas effacer sa propre trace.

## Journal du site demandé

Le propriétaire demande « un historique de tout ce qu’il se passe sur le site, des logs » ; la demande remplace le choix limité entre notifications de corrections.

Périmètre à couvrir dans le développement :

- Connexions, déconnexions et refus d’accès.
- Consultations des espaces, en distinguant la navigation humaine des rafraîchissements techniques automatiques.
- Créations, modifications, corrections, annulations et autres opérations métier.
- Lancements et récupérations des lots, avec leurs auteurs respectifs.
- Clôtures hebdomadaires et changements concernant les archives.
- Modifications des profils et des autorisations.
- Imports, synchronisations, exports et échecs importants.
- Pour chaque événement : date/heure, auteur identifié ou origine technique, action, objet concerné, résultat et, lorsque pertinent, valeurs avant/après.
- Ne pas enregistrer de tokens, de secrets ou de contenu brut des retours OAuth2.
- Conservation confirmée : aucune suppression automatique des logs. Les anciennes actions doivent rester consultables, indépendamment des clôtures hebdomadaires. Prévoir la pagination et inclure le journal dans les sauvegardes.

Prévoir une recherche et des filtres par date, membre, type d’action et dossier/lot. Le nouvel espace devra suivre la règle existante des nouvelles pages : accès réservé au propriétaire jusqu’à sa configuration dans le Conseil. La trace d’une action ne doit pas être modifiable par son auteur.

Le 24 octobre 2026, la preview intègre un journal permanent avec une page dédiée, filtrage et pagination, changements avant/après des opérations métier, profils et permissions, ainsi que les consultations, refus et erreurs. Il conserve les nouvelles actions sans purge automatique et survit aux imports et resets. Les anciens détails absents ne sont pas reconstitués. La synchronisation métier bidirectionnelle, les corrections réservées à leurs auteurs et les sauvegardes automatiques hors machine restent des travaux distincts.

## Notifications

- Aucune notification de correction par message privé Discord n’a été demandée : la réponse donnée porte sur le journal complet.


## Accès individuels et révocation propre au site — 25 octobre 2026

Le propriétaire demande et confirme un accès par personne, créé uniquement par lui, par pseudo et code, avec des catégories attribuées individuellement. Cette méthode complète Discord et remplace sur ce point la contrainte initiale Discord exclusivement. Aucun accès individuel ne donne le statut suprême ou la gestion des autorisations. Sans catégorie attribuée, seul Mon Registre est disponible.

Il peut également révoquer un compte sur le site sans modifier ses rôles sur Discord. Ce blocage persiste malgré une reconnexion, un changement de rôle, un import ou un reset métier. Les sessions sont supprimées, mais le compte et les logs conservés. La réactivation demande une nouvelle connexion. La rotation d’un code invalide l’ancien code et ses sessions. Voir ACCES-INDIVIDUELS.md.
