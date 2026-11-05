# Finition visuelle — 5 novembre 2026

Proposition locale corrigée, à valider visuellement par le propriétaire avant
adaptation au dépôt GitHub publié. Aucun déploiement Linux, publication GitHub,
redémarrage de service ou changement de données réelles.

## Changements

- Première proposition refusée par le propriétaire : trop plate, boutons clairs
  et modifications de mise en page jugés banals. Ces changements sont retirés.
- `static/theme-refinement.css` v2 ne modifie que les nuances : pétrole profond,
  reflets bronze patiné, ivoire chaud, transparences et bordures fines. Les fonds
  dégradés remplacés par des aplats dans la v1 sont rétablis.
- Gabarits, tailles, typographies, titres masqués dans le panorama, boutons fins,
  cadres biseautés, fumée et animations d’origine restaurés. La capture fournie
  par le propriétaire est la référence visuelle à préserver.
- En-tête du formulaire : espace réservé au bouton de fermeture pour éviter
  qu’un titre long recouvre sa zone cliquable.
- `static/index.html` charge cette finition ; `index.html` est régénéré selon la
  transformation de `scripts/sync_pages.py`. Ce dernier reste inchangé.
- Les changements déjà présents dans le dossier avant cette intervention sont
  conservés. Aucun JavaScript métier ou fichier backend n’a été modifié.

## Aperçu local

```powershell
node scripts/preview-design.mjs
```

Ouvrir <http://127.0.0.1:8093/#overview>. Ce serveur écoute uniquement sur loopback,
sert uniquement les ressources publiques de `static/` et active la démonstration
existante par une configuration temporaire dans les réponses HTTP. Aucun fichier
de configuration du site n’est réécrit ; ni `.env`, ni `data/` ne sont lus.
Le mode démonstration utilise les comportements locaux déjà prévus par le site.
Il ne remplace pas une recette du backend connecté avec de véritables permissions.

Les montants fictifs employés pendant les contrôles ont été injectés uniquement
en mémoire du navigateur ; aucun import du total historique n’a été effectué.

## Vérifications ciblées

Choix confirmé ensuite : **B Éclipse dorée**. Ajustement demandé par nouvelle
capture : retirer les faisceaux solaires et utiliser des anneaux segmentés,
graduations fines et reflets dorés de style futuriste. Variante modifiée dans
le comparateur et extraite dans `static/theme-eclipse.css`, sans les styles A/C
ni le paramètre de démonstration. Cette feuille est chargée en dernier par les
deux entrées HTML locales. Couleurs appliquées aux surfaces, contrôles et menus
partagés ; logique et variables de progression du compteur conservées. Aucun
transfert au dépôt Desktop et aucun déploiement Linux.

Nouvelle demande : comparer trois propositions plus sombres avec anneau lumineux
inspiré d’une capture, sans remplacer immédiatement le thème. Comparateur local
<http://127.0.0.1:8093/design-preview> : A Or patiné, B Éclipse dorée, C Bronze fumé.
Fichiers de préparation dans `scripts/design-preview/`, servis uniquement par
`scripts/preview-design.mjs` ; paramètres `?design=patine|eclipse|braise` validés
par liste fermée. Aucun ajout aux ressources chargées normalement par le site.
Compteur réel du frontend conservé avec données fictives en mémoire ; couleurs,
double anneau, reflets et rayons CSS sont propres aux aperçus. Contrôle des trois
variantes : chargement sans message d’erreur du site ni débordement horizontal
sur le viewport desktop ; syntaxe JS et diagnostics éditeur sans erreur. Aucune
recette complète revendiquée avant choix. La variante B est affichée initialement,
mais aucun choix n’est validé ni intégré au dépôt publié.

État final de la navigation d’aperçu : à la demande du propriétaire, entrée
« Accès extérieurs » supprimée. Rôles, autorisations et comptes sont regroupés
dans le Conseil ; les anciennes URL `#external-access` y redirigent. Version
demo v12, recherche/navigation sans doublon, réglages et comptes locaux conservés.
Vérification navigateur : entrée absente, redirection fonctionnelle et deux
blocs présents ; syntaxe des scripts valide. Test navigateur existant adapté.

Disposition du Conseil rétablie ensuite selon la capture du propriétaire :
`static/demo.js` conserve désormais `#individual-access` sous les autorisations,
au lieu de le retirer de la page Conseil. Les comptes restent également
consultables via le raccourci d’aperçu « Accès extérieurs ». Aucun changement de
permissions ni du code connecté. Comparaison préalable : 12 fichiers communs
du projet et du dépôt Desktop identiques, dont Conseil/comptes/styles/secure.
Entrées HTML actualisées (demo v11). Vérifié à 390 et 1440 px : titre des comptes,
position après les autorisations, aucune erreur affichée ni débordement. Les
comptes réels ne sont pas chargés dans cet aperçu.

Correction de l’aperçu : son ancien menu flottant « Gestion » ne reflétait pas
la navigation du site connecté. `static/demo.js` affiche désormais les liens
« Le Conseil des Accès » et « Accès extérieurs » directement en bas du menu.
`secure.js` et les permissions connectées sont inchangés. Version de `demo.js`
actualisée dans les deux entrées HTML ; contrôle correspondant adapté dans
`tests/browser_pages.mjs`. Vérifié dans le navigateur intégré à 390/1440 px :
liens en dernière position, ouverture des deux rubriques, absence de popover et
de débordement ; lot fictif conservé. Syntaxe des deux scripts valide. Le script
Chrome complet n’a pas été relancé pour cette correction ciblée.

Ajout v3 demandé ensuite : rétroéclairage champagne statique derrière le cadran
du lot, par pseudo-élément décoratif flouté. Aucun changement du compteur, de ses
dimensions ou des opérations. Présent sur les cadrans de lots partagés entre
tableau de bord et gestion des machines. Contrôlé à 320, 390 et 1440 px : aucun
débordement, lumière derrière le cercle et sans interception des clics.

État actuel v2 : 24 passages navigateur, soit 12 rubriques à 390 et 1440 px,
sans débordement, message d’erreur du site ou exception JavaScript. Dimensions,
polices et arrondis de cinq composants représentatifs comparés avec/sans la
finition v2 : identiques. Le lot fictif lancé à la demande du propriétaire est
resté visible. Aucune erreur CSS signalée par l’éditeur.

Les vérifications suivantes concernent la première proposition, désormais
remplacée ; elles ne constituent pas une nouvelle recette exhaustive de la v2 :

- Navigateur intégré : 12 rubriques à 320, 390, 768 et 1440 px, soit 48 passages,
  sans débordement horizontal, erreur JavaScript ou message d’erreur du site.
- 20 passages supplémentaires sur cinq rubriques aux mêmes largeurs avec un
  dossier, un lot et un cumul entièrement fictifs : aucun débordement ni message
  d’erreur du site.
- Ouverture et fermeture réelle du formulaire d’ajout, menu mobile puis navigation,
  recherche « Machines », focus clavier visible et préférence de mouvement réduit.
- Contrôles Node existants : `company_history.mjs`, `sales_subtotals.mjs` et
  `sales_progress.mjs` réussis. Syntaxe du serveur d’aperçu valide.
- Aucune erreur signalée par l’éditeur dans les fichiers modifiés de cette étape.
- Aucun test Python exécuté : pas d’environnement Python disponible ici.
- Le moteur automatique Impeccable est absent ; les consignes du skill ont été
  appliquées manuellement. Aucun résultat du détecteur automatique n’est revendiqué.

## Suite

Recueillir l’avis sur le rendu et ajuster si nécessaire. Après validation,
comparer les fichiers du dépôt Desktop `Vigneron-B` et y adapter seulement les
changements visuels compatibles. Ne pas copier les données ou configurations
Windows vers Linux ; la publication reste effectuée par le propriétaire.

## Compteur lumineux — variante B

La variante Éclipse dorée conserve le cadran et la taille existants. Le filet
extérieur et les accents en circuits restent décoratifs ; l'anneau SVG intérieur
seul représente la progression réelle. Le calcul `cyclePercent` alimente le
décompte, l'arc lumineux et la position de la boule à chaque actualisation du
cycle. La piste restante est sombre. Aucun identifiant SVG ni nouvelle durée de
cycle n'ont été introduits. La boule a un halo fixe et une pulsation légère,
désactivée avec la préférence de mouvement réduit.

Contrôle ciblé dans l'aperçu fictif : à 0, 25, 50, 75 et 100 %, l'arc SVG prend
exactement la valeur demandée ; l'écart géométrique entre son extrémité et la
petite boule reste sous 0,4 px. Vues de bureau et mobile (390 px) inspectées,
sans débordement horizontal. Syntaxe JavaScript, diagnostics de l'éditeur et
`git diff --check` vérifiés. Aucun déploiement, redémarrage ou transfert vers
le dépôt GitHub publié.

Retouche suivante demandée après comparaison avec la capture de référence :
le contour du cadran était trop réduit à des filets fins. Une couronne SVG
statique ajoute maintenant trois rayons concentriques, des segments de métal,
des filets lumineux, une ponctuation fine et quatre reflets localisés, dont
deux éclats horizontaux en haut et en bas. Les anciens traits décoratifs ont
été atténués pour laisser de la profondeur au fond. L'anneau SVG de
progression et sa boule restent indépendants de cette couronne décorative et
continuent de lire la progression réelle. Vérification ciblée du rendu à
1440 et 390 px : pas de débordement ; syntaxe JavaScript et diagnostics CSS
valides. Toujours aucune publication ni intervention sur le Site GitHub.

Survol des indicateurs : le découpage visuel du cadre reste appliqué au cadre
et à sa couche intérieure. Deux zones de survol transparentes interceptent les
coins gauche et droit, puis activent le reflet de la carte correspondante sans
laisser ce reflet déborder hors des angles coupés. Vérifié dans l'aperçu local
aux deux extrémités du bandeau.
Le reflet droit des cartes extrêmes créait une coupure verticale aux séparations
entre « Somme reçue » et « Montant traité », puis entre « Gain entreprise estimé »
et « Machines en activité ». Leur reflet conserve maintenant la même inclinaison
que les autres cartes et se prolonge de 20 px sous les coins extérieurs ; le cadre
coupe ce prolongement. Les deux jonctions ont été inspectées dans l'aperçu local.
La règle de sélection du texte ajoutée à tort lors de la première interprétation
du problème a été retirée. Les montants et leur calcul ne sont pas modifiés.
