# Évaluation de l'OCR (étape 5)

**Méthode.** 20 factures scannées ont été tirées au hasard ; pour chacune, 14 champs ont été vérifiés à la
main sur l'image (soit 280 valeurs, dans `verite_terrain.csv`). Chaque facture passe par la chaîne
OCR + parseur silver, à quatre résolutions. Une valeur est comptée juste seulement si elle est
exactement égale à la vérité terrain. Commande : `uv run python etape5_evaluation.py`.

| | 50 DPI | 72 DPI | 130 DPI | 200 DPI |
|---|---|---|---|---|
| Précision globale | 85,7 % | 100 % | 100 % | 100 % |
| Client | 50 % | 100 % | 100 % | 100 % |
| SIRET fournisseur | 55 % | 100 % | 100 % | 100 % |
| Numéro de facture | 75 % | 100 % | 100 % | 100 % |
| Montants (HT / TVA / TTC) | 95 à 100 % | 100 % | 100 % | 100 % |
| Temps par page | ≈ 6 s | ≈ 6 s | 8,3 s | 10,0 s |

**Analyse.**
- **Un seuil net à 72 DPI.** En dessous, la qualité chute ; au-dessus, elle ne progresse plus, mais le temps
  augmente (+20 % entre 130 et 200 DPI).
- **Les champs fragiles** sont les noms propres et les longues suites de chiffres, que le modèle ne peut pas
  deviner d'après le contexte : « Fleury » est lu « Finruy », un chiffre change dans un SIRET.
- **L'OCR se trompe sans prévenir** : 31 erreurs sur 40 sont des valeurs fausses mais plausibles.
  Les contrôles qualité du silver repèrent 13 des 18 factures erronées ; les 5 autres passeraient comme
  valides.

**Choix retenu : 130 DPI.** C'est la recommandation du modèle, avec 100 % de valeurs exactes et une marge
de sécurité pour des scans réels de moins bonne qualité.

**Limites.** L'échantillon est petit (20 factures), les scans sont propres, et chaque réglage n'a été
testé qu'une fois. « 100 % » ne veut pas dire « zéro erreur ».
