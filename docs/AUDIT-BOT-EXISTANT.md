# Analyse du bot existant — 28 octobre 2026

Code examiné : `C:\Users\Dojojo\Pictures\bot_blanchiment`.
Le bot en service sur Linux est indiqué dans son README comme
`blanchimentbot.service`, avec `bot.py` comme programme principal.

Cette analyse porte sur les sources. Elle ne lance pas le bot et ne vérifie pas
le déploiement Linux. Les `.env`, la clé Google, les bases et les données JSON
réelles n'ont pas été consultés. Aucun fichier du bot n'a été modifié.

## Pourquoi le bouton du site ne lance rien dans Discord

Dans le site, `backend/app.py` enregistre d'abord l'opération dans sa propre
base. `backend/bot_bridge.py` ajoute ensuite une commande à la file uniquement
si `HERITAGE_BOT_COMMANDS_ENABLED=1`. Avec `0`, l'enregistrement reste sur le site.

Le transport `connectors/website_client.py` sait lire et confirmer cette file.
Le bot fourni ne l'importe pas et ne contient aucun gestionnaire des commandes
du site. L'exemple `handle_site_command` dans `CONNEXION-BOT.md` est encore un
exemple non implémenté. La connexion Discord et la récupération des grades ne
déclenchent donc pas les opérations du bot.

## Ce que fait déjà un lancement dans le bot

Dans `bot.py`, `MachineModal.on_submit` :

1. Vérifie le montant : 1 000 000 $ par défaut et au maximum.
2. Appelle `add_machine_to_sheet` pour enregistrer le montant, la date,
   l'heure et le nom dans le stockage configuré.
3. Envoie la carte Discord avec `MachineLaunchView` et la mention du rôle prévu.
4. Sauvegarde le rappel avec l'ID de l'utilisateur, l'ID du message Discord,
   la référence de stockage, l'heure de lancement et celle de fin.
5. Appelle `increment_machine_stat` et `schedule_reminder` pour le compteur
   et le rappel de 4 h 45.

La récupération et l'annulation utilisent notamment `MachineRecoveredView`,
`set_machine_recovered_state`, `refresh_known_machine_status_messages` et
`decrement_machine_stat`. Elles doivent conserver le lien avec la même machine.

`add_machine_to_sheet` utilise le stockage local lorsque ce mode est configuré,
sinon Google Sheets. Le raccordement doit réutiliser ce choix existant.

## Blanchiment et configuration

`SaleAmountModal.on_submit` utilise `add_sale_to_sheet`, publie la fiche Discord
et la relie à son auteur avec `register_sale_message(..., creator_id=...)`.
Les modifications, restitutions et statuts passent notamment par
`EditSaleModal`, `FinishSaleModal`, `SaleStatusView`, `edit_sale_sheet`,
`finish_sale_sheet` et `update_sale_status_sheet`.

Le donneur possède un identifiant RP distinct de l'ID Discord de l'auteur.
Ces deux identifiants ne doivent pas être déduits l'un de l'autre.

`bot_setup/` est une interface de configuration indépendante. Son API gère les
réglages, ressources, stockages et panneaux des serveurs ; elle ne propose pas
le lancement des opérations du site.

## Points à respecter pour le raccordement

- Conserver le client Discord existant. `bot_guilds.py` crée des contextes
  séparés pour chaque serveur et remplace les méthodes de démarrage du bot.
  Un ajout uniquement dans le `on_ready` principal peut donc être contourné
  par ce mode. Le raccordement doit utiliser le bon contexte de serveur.
- Extraire une fonction métier commune au formulaire Discord et au site.
  Les callbacks actuels demandent une vraie `discord.Interaction`, répondent
  à un formulaire et capturent leurs erreurs. Les appeler comme un gestionnaire
  HTTP risquerait de confirmer à tort une action qui a échoué.
- Utiliser l'ID de l'auteur transmis par la session du site, puis vérifier le
  serveur et le membre avant l'exécution. Ne pas remplacer cet ID par celui du
  propriétaire ou du bot. Les comptes extérieurs sans membre Discord doivent
  avoir un comportement explicitement défini avant de leur ouvrir ce parcours.
- Conserver durablement la correspondance entre ID de commande du site,
  machine du bot, référence de stockage et message Discord. Une relivraison
  ne doit pas ajouter un nouveau lancement ou incrémenter à nouveau le compteur.
- Prévoir les échecs partiels : le lancement actuel écrit dans le stockage
  avant d'envoyer son message Discord. Un simple nouvel appel après une panne
  peut donc écrire deux fois. Les confirmations doivent suivre l'exécution
  vérifiée, avec reprise ou rapprochement des étapes déjà effectuées.
- Partager le contrôle des lancements simultanés entre les boutons Discord
  et le site, et synchroniser les changements dans les deux sens.
- Distinguer dans l'interface un enregistrement sur le site, une commande
  en attente du bot et une exécution confirmée. Un compteur local ne prouve
  pas qu'un message a été publié sur Discord.

Changer une variable `.env` ou copier uniquement `website_client.py` ne suffit
pas : le gestionnaire métier et son démarrage dans le bot restent à implémenter.
Les anciens essais faits avec les échanges désactivés ne sont pas mis en file
automatiquement après leur activation.
