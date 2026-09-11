# Gestionnaire d'Achat Immobilier & Travaux 🏠

Application développée avec **Streamlit** pour piloter un projet d'achat immobilier et de rénovation/extension en France.

## Fonctionnalités
- **Suivi des devis** : Ajout manuel ou extraction automatique des montants depuis des fichiers PDF, avec sélection et validation par case à cocher pour intégrer dynamiquement les postes au budget global.
- **Simulation de financement** : Calcul des mensualités (avec ou sans assurance), vérification du taux d'endettement par rapport aux normes françaises (HCSF) et estimation du reste à vivre.
- **Estimation de la plus-value** : Calcul de la revente avec prise en compte de la fiscalité française (résidence principale ou secondaire, abattements pour durée de détention et surtaxes).
- **Tableau de bord** : Visualisation graphique des coûts et des statuts d'avancement.

## Prérequis
- Python 3.9 ou supérieur

## Installation
1. Cloner ou télécharger le projet.
2. Installer les dépendances :
   ```bash
   pip install -r requirements.txt
