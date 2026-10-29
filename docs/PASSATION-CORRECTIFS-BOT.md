# Correctifs du bot avant la recette Machines

Le site a intégré le protocole `machines-v1` du dossier
`recap/raccordement-machines-2026-10-29`. Les fichiers de ce dossier sont un
instantané à conserver ; ils ne remplacent pas les fichiers du site qui ont
depuis conservé/corrigé les sessions, l'attribution et les calculs financiers.
Le bot et la production Linux n'ont pas été modifiés pendant cette fusion.

## Texte à transmettre à la conversation du bot

Tu reprends l'implémentation Machines déjà existante dans mon bot. Fais des
correctifs ciblés, puis teste-les avec Discord/Google simulés et des données
temporaires. Conserve les commandes, messages et rappels existants.

### 1. Reprise d'une demande avant son premier effet — défaut reproduit

Dans `machine_operations.py`, le contrôle du lot précédent n'est effectué que
lors de la création du journal dans `MachineOperations.execute`. Une reprise
qui recharge un état `stage=new` passe directement à `launch`, sans refaire
ce contrôle sous le verrou commun.

Reproduction isolée effectuée côté site avec le vrai moteur fourni et des
effets simulés :

1. A demande un lancement. La recherche réseau du salon échoue avant tout effet ;
   le journal de A reste à `new`.
2. B lance depuis Discord : le lancement réussit et le lot est actif.
3. A est relivrée : elle crée actuellement un deuxième lot actif.

Ajoute un test qui reproduit ce scénario et corrige-le. Revalide les
préconditions courantes avant le premier effet d'une reprise, sous le même
verrou que les lancements Discord. Une demande refusée ne doit ni créer une
ligne ni envoyer une carte ni incrémenter le compteur. Conserve un état de
journal cohérent pour les prochaines reprises/clôtures.

Vérifie également l'heure réelle : une demande restée à `new` pendant une panne
ne doit pas publier plus tard un nouveau lancement daté de plusieurs heures
avant son exécution. Les reprises après effets déjà prouvés doivent conserver
leurs vrais horaires et leurs identifiants.

### 2. Écrivains concurrents des rappels

Le moteur commun utilise un verrou mais `reminder_worker`,
`machine_recovery_repeat_loop` et la restauration historique peuvent encore
charger un objet/une liste, attendre Discord puis sauvegarder cet ancien état.
Cela peut écraser une récupération, une annulation, une nouvelle machine ou
des références de message enregistrées pendant l'attente.

Inventorie les écrivains du suivi et organise leurs mutations avec le même
mécanisme de cohérence. Après un appel réseau, recharge l'état et fusionne
uniquement les champs réellement produits par le worker. Ne réécris pas une
ancienne liste complète et ne remplace pas une machine par un objet périmé.
Préserve les états récupéré/annulé et le véritable auteur.

Ajoute des tests contrôlant les entrelacements réseau/mutations, y compris une
récupération ou annulation pendant l'envoi d'un rappel. Respecte aussi le salon
durable de la machine lors d'un changement de configuration.

### 3. Résolution des états incertains

Le moteur peut adopter une ligne avec `adopt_storage`, mais l'inbox du
connecteur et le job du site peuvent déjà être terminaux `uncertain`. Adopter
la ligne seule ne rouvre pas ces autres journaux.

Décris et prépare un parcours de résolution administratif, authentifié,
audité et idempotent qui coordonne ces états. Il faudra convenir de son contrat
avec le site avant de l'exposer. Ne supprime pas les bases de déduplication,
ne transforme pas un échec en succès sans preuve et ne relance pas avec un
nouvel identifiant pour contourner le blocage.

### 4. Contrat du site à préserver

- Les routes internes restent `/internal/bot/commands`, `/internal/bot/events`
  et `/internal/bot/ack`, signées avec le client existant.
- `body.version=2`, `body.protocol=machines-v1` ; les demandes utilisateur
  retournent `pending:true`, sans créer de machine confirmée.
- Les snapshots utilisent `kind=machine_sync`, `siteRecordId` et une révision
  persistante. `commandId` est facultatif dans le snapshot, obligatoire dans
  l'ACK d'une demande.
- Un ACK `applied` doit contenir `result.machine`. Le site vérifie l'auteur et
  le montant du lancement, et l'état demandé pour recover/unrecover/cancel.
- Un ACK terminal redélivré conserve le même statut, résultat et erreur.
- Le `MachineWebsiteBridge` livré fournit déjà le résultat canonique : garde
  ce consommateur durable, sans le remplacer par le helper générique `poll`.
- Le site préserve les profils et les brouillons au retour d'onglet. Ne lui
  recopier aucun ancien `secure.js` depuis le récapitulatif.
- Les anciennes machines d'essai ne comptent plus dans les allocations et
  montants traités en mode connecté. La réinitialisation ne peut plus effacer
  des machines liées ou des demandes de raccordement.

### 5. Restitution attendue

Donne la liste exacte des fichiers du bot modifiés, les tests exécutés et leurs
résultats, les éventuels changements du contrat, les limites restantes et les
fichiers à transférer sur Linux. Ne touche pas aux drapeaux privés, au service,
aux opérations métier réelles ou au site déployé pour faire les tests.

Une recette réelle site → bot → Discord → site, puis le rappel après 4 h 45,
restera à effectuer sur une véritable opération après ces corrections.

## Vérifications effectuées sur cette fusion du site

- Tests ciblés protocole, attribution et finances : 53 réussis.
- Dernière suite générale : 318 réussis, 3 ignorés, un échec de fixture FIFO.
  Cette fixture représentait une machine traitée sans son statut confirmé ;
  elle a été corrigée. Le fichier concerné et les régressions financières ont
  ensuite été revérifiés : 23 tests réussis. Ne pas présenter ces résultats
  comme une nouvelle passe générale unique de 319 tests.
- Chrome : accueil, connexion, navigation et affichage 320/390/768/1440 px
  réussis ; retour d'onglet, brouillons, erreurs réseau, expiration et retrait
  de droits réussis, sans erreur JavaScript.
- Tests Node du rafraîchissement Machines, de la connexion et des essais locaux
  réussis. La syntaxe JS et les différences Git ont été vérifiées.
- Le contrat croisé exige un checkout du bot et `discord.py` ; il reste ignoré
  dans cet environnement du site. Aucun lancement Discord/Google réel ni
  redémarrage de production n'a été exécuté.
