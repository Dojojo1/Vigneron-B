# Adresse fixe et demarrage automatique sur Linux

Adresse publique choisie : `https://unabashed-tackle-claw.ngrok-free.dev`.
Le domaine est attribue au compte ngrok ; le PC et le serveur Python doivent
rester allumes. L'offre gratuite conserve ses quotas et sa page d'avertissement.
Le bot utilise toujours `HERITAGE_SITE_URL=http://127.0.0.1:8081` sur ce meme PC.

## Configurer ngrok

La configuration privee existante se trouve ici :
`/home/dojojo/.config/ngrok/ngrok.yml`. Ne pas publier ce fichier ni son jeton.

Ouvrir le fichier avec `nano /home/dojojo/.config/ngrok/ngrok.yml`.
Utiliser la structure de [l'exemple sans secret](../deploy/ngrok.example.yml)
en conservant le vrai jeton local. Dans la version 3, `authtoken` est place sous
`agent`. Les autres options personnelles de l'agent doivent etre conservees.
Ne pas ajouter de connexion Google ou de politique de filtrage d'exemple.

Verifier la syntaxe avant de modifier le service :

```bash
ngrok config check --config /home/dojojo/.config/ngrok/ngrok.yml
```

Arreter avec Ctrl+C le tunnel ngrok lance manuellement. Pour remplacer le service
recemment installe avec le mauvais chemin `./ngrok.yml` :

```bash
sudo ngrok service uninstall
sudo ngrok service install --config /home/dojojo/.config/ngrok/ngrok.yml
sudo systemctl enable --now ngrok.service
systemctl is-active ngrok.service
```

Le resultat attendu est `active`. En cas d'echec :

```bash
journalctl -u ngrok.service -n 30 --no-pager
```

## Configurer le site une seule fois

Sur Linux, avec les scripts a jour :

```bash
cd /home/dojojo/Documents/vigneron_site
.venv/bin/python scripts/configure_connection.py --url https://unabashed-tackle-claw.ngrok-free.dev
```

Cette commande actualise uniquement les deux origines du `.env` prive et le JSON
public. Les variables exportees dans l'environnement du processus restent
prioritaires : retirer toute ancienne origine exportee avant de relancer le site.

Dans le portail developpeur Discord, pour l'application du site, ajouter dans
OAuth2 > Redirects puis enregistrer :
`https://unabashed-tackle-claw.ngrok-free.dev/auth/callback`.

Publier le `static/site-config.json` actualise sur GitHub Pages. Les mises a jour
du code sur GitHub doivent aussi etre transferees vers le dossier du site Linux.
Le serveur Python doit etre redemarre apres modification de ses origines privees.

## Demarrer aussi le serveur Python au demarrage du PC

Le modele ci-dessous est prepare pour l'utilisateur `dojojo`, le dossier
`/home/dojojo/Documents/vigneron_site` et son environnement `.venv`.
Arreter d'abord le serveur Python manuel avec Ctrl+C pour liberer le port 8081.
Installer ensuite ce service depuis le dossier du site mis a jour :

```bash
sudo install -m 644 deploy/heritage-site.service /etc/systemd/system/heritage-site.service
sudo systemctl daemon-reload
sudo systemctl enable --now heritage-site.service
systemctl is-active heritage-site.service
curl -sS --max-time 5 http://127.0.0.1:8081/api/status
```

Le callback retourne doit correspondre a l'adresse ngrok fixe. Pour les futures
mises a jour Python : `sudo systemctl restart heritage-site.service`.
Le service Discord existant `blanchimentbot.service` n'est pas modifie.

## Verification finale

Verifier les deux services, puis ouvrir l'adresse publique et se connecter avec
Discord. La page d'avertissement ngrok gratuite peut demander de cliquer sur
Visit Site avant la premiere ouverture. Ces controles ne lancent aucune machine.

```bash
systemctl is-enabled ngrok.service heritage-site.service
systemctl is-active ngrok.service heritage-site.service
```

Documentation officielle :
- [Configuration ngrok version 3](https://ngrok.com/docs/gateway/agent/config/v3)
- [Agent ngrok comme service](https://ngrok.com/docs/gateway/agent/service)
- [Domaine de developpement attribue](https://ngrok.com/blog/free-static-domains-ngrok-users)
