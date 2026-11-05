# Déploiement du cahier des charges — à exécuter après validation

Les corrections se trouvent dans les trois dossiers de `C:\Users\Dojojo\Documents\codex`. Le déploiement de production n'a pas été exécuté. Conserver le même bot Discord et le service `blanchimentbot.service` existant.

## 1. Sauvegarde du PC Linux avant remplacement

Arrêter les modifications métier pendant cette opération. Si le Site Linux est encore lancé à la main, l'arrêter avec Ctrl+C dans son terminal ; s'il est déjà géré par systemd, arrêter son service existant. Arrêter brièvement le bot pour obtenir un ensemble cohérent de JSON et de bases. Une sauvegarde doit couvrir les **fichiers du PC Linux**, plus récents que les copies Windows.

Copier uniquement le nouveau script `scripts/backup_runtime.py` du Site Linux vers le PC Linux avant cette étape, puis exécuter :

```bash
sudo systemctl stop blanchimentbot.service
cd /home/dojojo/Documents/vigneron_site
umask 077
.venv/bin/python scripts/backup_runtime.py \
  --site /home/dojojo/Documents/vigneron_site \
  --bot /home/dojojo/Documents/bot_blanchiment \
  --destination "/home/dojojo/sauvegardes-heritage/avant-cahier-$(date +%Y%m%d-%H%M%S)"
```

Garder aussi une copie privée des sources Linux actuellement installées et de la configuration du service ngrok. Le script protège les données et secrets ; sa destination ne doit jamais être publiée sur GitHub. Si une commande échoue, conserver les anciennes sources et redémarrer le bot avant de poursuivre le diagnostic.

## 2. Bot Discord (`bot_blanchiment`)

Transférer les sources modifiées du dossier Bot Discord vers `/home/dojojo/Documents/bot_blanchiment`, notamment :

- `bot.py`, `bot_guilds.py`, `machine_operations.py`, `bot_website_bridge.py` ;
- nouveaux `business_operations.py`, `bot_business_bridge.py` ;
- le client de raccordement et autres fichiers listés dans `CODEX_MODIFICATIONS.json` si modifiés.

**Ne pas remplacer les données Linux par les données Windows** : conserver `.env`, fichiers JSON d'opérations, répertoires de stockage par serveur, bases SQLite, clés et identifiants privés existants. Ne pas lancer un deuxième bot. Ne pas modifier les paramètres Google Sheets ou salons déjà configurés sans raison.

Dans le `.env` privé du bot :

```dotenv
HERITAGE_SITE_URL=http://127.0.0.1:8081
```

Conserver le secret de raccordement déjà partagé avec le Site Linux. Le bot et le serveur Python étant sur le même PC Linux, leurs échanges internes restent locaux ; ils n'ont pas besoin de passer par ngrok. Le bot doit pouvoir lire les membres et modifier/envoyer les cartes dans les salons configurés pour chaque module.

## 3. Site Linux (`vigneron_site`)

Transférer les sources modifiées du Site Linux vers `/home/dojojo/Documents/vigneron_site` : `backend/`, `connectors/` s'il comporte des changements, `static/`, `scripts/` et `deploy/`. Utiliser la liste de modifications commune. Conserver sa base `data/heritage-test.sqlite3`, ses avatars, clés et fichiers privés Linux. Le nom historique de la base ne signifie pas qu'elle peut être effacée.

Dans son `.env` privé, conserver les tokens/identifiants et vérifier :

```dotenv
HERITAGE_BASE_URL=https://unabashed-tackle-claw.ngrok-free.dev
HERITAGE_PUBLIC_BACKEND_URL=https://unabashed-tackle-claw.ngrok-free.dev
HERITAGE_LOCAL_PREVIEW=0
HERITAGE_BOT_COMMANDS_ENABLED=1
HERITAGE_BUSINESS_COMMANDS_ENABLED=1
```

Le nouveau commutateur métier s'active uniquement avec la nouvelle version du bot. Le secret de raccordement doit rester identique dans les deux fichiers privés. Les variables déjà exportées dans le terminal ont priorité sur `.env` : ne pas conserver d'ancien `HERITAGE_BASE_URL` exporté.

```bash
cd /home/dojojo/Documents/vigneron_site
.venv/bin/python scripts/configure_connection.py --url https://unabashed-tackle-claw.ngrok-free.dev
```

Pour démarrer le Site Linux automatiquement, après avoir arrêté toute instance manuelle écoutant déjà sur 8081 :

```bash
sudo install -m 644 deploy/heritage-site.service /etc/systemd/system/heritage-site.service
sudo systemctl daemon-reload
sudo systemctl enable --now heritage-site.service
sudo systemctl restart blanchimentbot.service
systemctl status heritage-site.service blanchimentbot.service --no-pager
curl -fsS --max-time 5 http://127.0.0.1:8081/api/status
```

Les ajouts de tables SQLite sont réalisés au démarrage ; ils ont été répétés sur des copies temporaires sans modifier les lignes existantes. La sauvegarde préalable reste nécessaire.

## 4. Tunnel ngrok constant

Le service exposé est **le Site Linux sur 8081**, pas le processus du bot. Le générateur lit le jeton déjà enregistré dans le fichier privé ngrok, puis crée `data/ngrok.yml` complet avec `version: 3`.

```bash
cd /home/dojojo/Documents/vigneron_site
.venv/bin/python scripts/configure_ngrok.py --credentials /home/dojojo/.config/ngrok/ngrok.yml
ngrok config check --config /home/dojojo/Documents/vigneron_site/data/ngrok.yml
```

Si le jeton n'existe plus dans le fichier privé actuel, l'enregistrer localement avec `ngrok config add-authtoken` en suivant le tableau de bord ngrok ; ne pas transmettre sa valeur dans les rapports. Relancer ensuite le générateur. Ne pas remplacer les paramètres existants à l'aveugle.

Après réussite du contrôle, arrêter le tunnel lancé à la main. Le service ngrok installé précédemment pointait sur un fichier absent dans le dossier du bot ; remplacer son installation uniquement si `systemctl cat ngrok.service` confirme qu'il s'agit bien de ce service :

```bash
sudo systemctl stop ngrok.service
sudo ngrok service uninstall
sudo ngrok service install --config /home/dojojo/Documents/vigneron_site/data/ngrok.yml
sudo systemctl daemon-reload
sudo systemctl enable --now ngrok.service
systemctl status ngrok.service --no-pager
```

Si aucun service ngrok n'est installé, sauter les deux commandes d'arrêt/désinstallation. Ne pas démarrer simultanément le tunnel manuel et le service sur la même adresse.

La configuration v3 et l'exécution comme service sont décrites dans la [documentation ngrok](https://ngrok.com/docs/gateway/agent/config/v3). Le domaine attribué au compte reste fixe, mais les quotas du forfait gratuit s'appliquent ; surveiller la [page Usage](https://dashboard.ngrok.com/usage) et les [limites officielles](https://ngrok.com/docs/pricing-limits/free-plan-limits). Une adresse fixe ne garantit pas une disponibilité illimitée si le PC dort, perd Internet ou atteint un quota.

## 5. Connexion Discord et Site GitHub (`Vigneron-B`)

Dans Discord Developer Portal, enregistrer exactement ce retour OAuth2 :

```text
https://unabashed-tackle-claw.ngrok-free.dev/auth/callback
```

Conserver le Client ID et le Client Secret actuels dans les fichiers privés. Le rôle employé et les rôles de gestion restent ceux configurés sur le serveur.

Pour le Site GitHub, publier les ressources publiques corrigées du dossier **Site GitHub (`Vigneron-B`)** : `index.html`, `static/` et la configuration publique `static/site-config.json`. Ne pas publier `.env`, `data/`, sauvegardes, clés, jetons ou bases. Ne pas copier le `index.html` du Site Linux à la place de celui prévu pour GitHub Pages.

**Mettre uniquement GitHub à jour ne met pas à jour les fichiers servis par le Site Linux après connexion.** Il faut transférer les deux ensembles de ressources vers leur destination respective.

## 6. Vérifications après déploiement

Sans effectuer de mutation :

```bash
curl -fsS --max-time 10 https://unabashed-tackle-claw.ngrok-free.dev/api/status
journalctl -u heritage-site.service -u blanchimentbot.service -u ngrok.service -n 80 --no-pager
```

Le retour OAuth2 doit contenir le domaine ngrok actuel. Une erreur `Invalid host header` indique que le Site Linux tourne encore avec une origine différente ou un ancien processus ; vérifier sa configuration et le redémarrer, sans désactiver le contrôle Host. Une page d'avertissement ngrok peut apparaître pour les visiteurs du forfait gratuit ; suivre le lien de continuation avant la connexion Discord.

Puis, dans un périmètre de test approuvé :

1. Se connecter avec deux membres distincts ; vérifier surnoms serveur et droits.
2. Lancer un lot depuis le Site Linux, vérifier auteur, carte Discord et compteur ; modifier son heure, annuler, relancer.
3. Annuler depuis Discord et vérifier la libération sur le Site Linux après synchronisation.
4. Revenir après inactivité, vérifier que les données restent présentes et se resynchronisent.
5. Créer/modifier/annuler un dossier et vérifier sa ligne dans le stockage configuré, sa carte et les indicateurs.
6. Ajouter deux véhicules, payer, supprimer un véhicule puis une semaine ; vérifier les cartes actualisées et l'absence de doublon.
7. Redémarrer les services et vérifier la conservation des opérations, puis le démarrage automatique du PC Linux.

Une opération marquée en attente ou incertaine ne doit pas être considérée comme réussie. Consulter les journaux avant toute nouvelle tentative susceptible de doubler un envoi. Ne pas utiliser de vraies opérations clients pour ces vérifications sans accord.

## Retour arrière

Arrêter les composants concernés, remettre les sources précédentes et la configuration privée sauvegardée, puis redémarrer. Les nouvelles tables sont additives : ne pas effacer la base pour revenir à l'ancienne interface. Si de nouvelles opérations ont été exécutées après déploiement, ne pas restaurer une ancienne base sans rapprochement préalable, au risque de perdre ces opérations ou de les rejouer.
