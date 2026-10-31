# Organisation à respecter

Ces règles s’appliquent aux prochains changements. Conserver les fonctionnalités,
les données et la direction artistique existantes. Modifier uniquement le projet concerné.

- Ranger les tests dans `tests/`, les outils dans `scripts/`, les guides dans `docs/`
  et les modèles de services dans `deploy/`.
- Les données durables vont dans `data/`. Les ressources livrées avec le programme
  vont dans `resources/` pour le bot et `static/` pour le site.
- Les secrets ne doivent jamais être publiés ou placés dans un dossier public.
  Le `.env` reste le point d’entrée standard de la configuration privée.
- Ne pas ajouter de copie ancienne, ZIP de passation, cache ou sortie de test
  à la racine. Réutiliser les dossiers de sauvegarde privés existants.
- Avant de déplacer un fichier utilisé, retrouver ses lecteurs et rédacteurs,
  adapter leurs chemins, sauvegarder puis tester la reprise. Une migration ne
  doit jamais écraser une destination déjà occupée ni réinitialiser une base.
- Les sources Windows ne remplacent jamais les données actuelles du PC Linux.
- Distinguer le Site Linux (`vigneron_site`), le Site GitHub (`Vigneron-B`)
  et le bot (`bot_blanchiment`). Ne pas supposer leurs copies identiques.
- Ne pas effectuer d’envoi Discord ou de modification Google pour tester sans
  instruction explicite ; utiliser les fixtures et transports simulés.

## Particularités du site

- Serveur dans `backend/`, interface et médias dans `static/`.
- Les données, sessions et avatars restent dans `data/`, hors du dépôt public.
- GitHub Pages sert l’accueil statique ; les comptes et données réelles sont
  fournis par le Site Linux. Le code et le setup du bot restent dans leur projet.
- Préserver les différences entre les copies du Site Linux et du Site GitHub.
