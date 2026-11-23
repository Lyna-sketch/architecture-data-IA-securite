# Évaluation de la qualité de l'OCR (étape 5)

## Méthode

**Vérité terrain.** 20 factures tirées au hasard (graine fixe, donc tirage reproductible) parmi les 50 factures
scannées. Pour chacune, 14 champs : numéro, fournisseur, SIRET fournisseur, client, SIRET client,
dates d'émission et d'échéance, catégorie, statut, mode de paiement, totaux HT / TVA / TTC, nombre de lignes,
soit **280 valeurs**.
Pour aller vite sans perdre en fiabilité, le fichier a été **pré-rempli** avec les valeurs extraites,
puis **chaque valeur a été vérifiée à l'œil** sur l'image de la facture. Aucune correction n'a été
nécessaire. Le fichier vérifié (`verite_terrain.csv`) est versionné dans le dépôt.

**Mesure.** Pour chaque résolution, chaque facture est passée à l'OCR (LightOnOCR-3-1B), puis le texte
obtenu est analysé par **le même parseur que la couche silver**. On mesure donc la qualité de toute la
chaîne OCR + extraction. Une valeur est comptée juste seulement si elle est **exactement** égale à la
vérité terrain.

**Réglages comparés.** 50, 72, 130 et 200 DPI. Pour une page A4, cela donne une image dont le plus
grand côté mesure 585, 842, 1521 et 2339 pixels. 130 DPI correspond à la recommandation de la fiche du
modèle (plus grand côté de 1540 px).

Commande pour reproduire : `uv run python etape5_evaluation.py`

## Résultats

| Champ | 50 DPI | 72 DPI | 130 DPI | 200 DPI |
|---|---|---|---|---|
| client | 50 % | 100 % | 100 % | 100 % |
| siret_fournisseur | 55 % | 100 % | 100 % | 100 % |
| numero_facture | 75 % | 100 % | 100 % | 100 % |
| siret_client | 85 % | 100 % | 100 % | 100 % |
| date_echeance | 85 % | 100 % | 100 % | 100 % |
| categorie | 85 % | 100 % | 100 % | 100 % |
| mode_paiement | 90 % | 100 % | 100 % | 100 % |
| nb_lignes | 90 % | 100 % | 100 % | 100 % |
| date_emission | 95 % | 100 % | 100 % | 100 % |
| total_ht | 95 % | 100 % | 100 % | 100 % |
| total_ttc | 95 % | 100 % | 100 % | 100 % |
| fournisseur | 100 % | 100 % | 100 % | 100 % |
| statut_paiement | 100 % | 100 % | 100 % | 100 % |
| total_tva | 100 % | 100 % | 100 % | 100 % |
| **Ensemble** | **85,7 %** | **100 %** | **100 %** | **100 %** |
| Temps OCR moyen par page | ≈ 6,4 s * | ≈ 6,2 s * | 8,3 s | 10,0 s |

\* Temps mesuré sur une seule page (essai de l'étape 2) ; les autres temps sont des moyennes sur 20 pages.

## Analyse

**Un seuil net.** À partir de 72 DPI, les 280 valeurs sont toutes exactes. À 50 DPI, 40 valeurs sont
fausses, et seules 2 factures sur 20 sont lues sans aucune erreur. Augmenter la résolution au-delà du
seuil n'améliore plus la qualité, mais augmente le coût : de 130 à 200 DPI, le temps passe de
8,3 à 10,0 s par page (+20 %), et l'image envoyée est 2,2 fois plus lourde.

**Les champs les plus fragiles** sont ceux que le modèle ne peut pas deviner d'après le contexte :
- **les noms propres** (client : 50 %) : « Fleury » est lu « Finruy », « Torres » est lu « Tonex », « Mace S.A. » est lu « Marie S.A. » ;
- **les longues suites de chiffres** (SIRET : 55 %, numéro de facture : 75 %) : un chiffre change
  (4874016**48**59826 devient 4874016**46**58626), et 2025 devient 2**5**25 dans les numéros ;
- **les dates** : le mois change (12/**08**/2025 est lu 12/**06**/2025).

Les champs **robustes** sont ceux qui n'ont que quelques valeurs possibles ou des mots courants :
statut (Payée / En retard / En attente), nom du fournisseur, taux de TVA.

**L'OCR se trompe sans prévenir.** Sur les 40 erreurs à 50 DPI, **31 sont des valeurs fausses mais
plausibles** et seulement 9 sont des champs vides. Contrairement à un OCR classique, qui produit des
caractères illisibles, un modèle de langage de vision « invente » une valeur crédible.
C'est le principal risque de cette technologie.

**Les contrôles qualité ne suffisent pas à tout rattraper.** Sur les 18 factures contenant au moins une
erreur à 50 DPI, les contrôles de la couche silver en repèrent 13 : SIRET qui n'a pas 14 chiffres,
HT + TVA ≠ TTC, champ manquant… Les **5 autres seraient acceptées comme valides**, par exemple un nom de
client faux avec des montants justes. Les contrôles arithmétiques protègent bien les montants, mais rien
ne permet de vérifier un nom propre.

## Conclusion et choix retenu

Nous retenons **130 DPI**. Ce réglage respecte la recommandation du modèle, donne 100 % de valeurs exactes
sur notre échantillon, et garde une marge par rapport au seuil de 72 DPI. Cette marge sera nécessaire
pour de vrais scans, plus flous, penchés ou mal contrastés que ceux du jeu fourni. 200 DPI n'apporte
rien de plus et coûte 20 % de temps.

## Limites

- **Taille de l'échantillon** : 20 factures, donc 20 valeurs par champ. Une seule erreur représente déjà 5 %.
  L'échantillon suffit pour voir un écart net (50 % contre 100 %), mais pas pour mesurer un taux d'erreur
  rare : « 100 % » signifie seulement « moins d'environ 1 erreur sur 280 dans ces conditions ».
- **Scans propres** : les factures du jeu sont droites et nettes. Il faudrait refaire l'évaluation sur des
  scans dégradés (flou, rotation, taches).
- **Un seul passage** par réglage : la variabilité du modèle d'un appel à l'autre n'est pas mesurée.
- **Mise en forme variable** : pour une même page, le modèle produit le bloc des totaux tantôt en texte,
  tantôt en tableau HTML, selon la résolution. Le parseur a dû être écrit pour accepter les deux formes.
