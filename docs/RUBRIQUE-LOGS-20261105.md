# Rubrique Logs

La rubrique `#logs` est distincte du Journal permanent. Elle reste vide jusqu'à
ce que le bot envoie ses propres logs lors d'un futur raccordement. Aucun flux
du bot, stockage de logs ou donnée fictive n'est ajouté par cette étape.

Le site connecté vérifie l'autorisation `logs` comme pour les autres pages
privées. Le Conseil des Accès peut l'accorder séparément. L'API renvoie une liste
vide ; la prévisualisation affiche le même état d'attente. Les données Linux,
le bot, Discord et Google ne sont pas modifiés.

Vérification locale ciblée : `tests/test_permanent_journal.py` — 14 tests réussis.
La copie GitHub publiée n'a pas reçu cette rubrique et aucun déploiement n'a eu lieu.
