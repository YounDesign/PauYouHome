# 🏠 Gestion d'achat immobilier & travaux

Application Streamlit pour piloter l'achat d'une maison (ou une extension /
rénovation) : devis avec PDF joints, simulation de financement avec taux
d'endettement français, et estimation de la plus-value à la revente.

## Fonctionnalités

- **Achat** : prix d'achat, frais de notaire paramétrables, coût total du projet.
- **Devis & travaux** : ajout de devis par catégorie, upload de PDF (le montant
  est détecté automatiquement si `pdfplumber` est installé — sinon saisie
  manuelle), suivi du statut, valeur ajoutée estimée par poste, graphique de
  répartition du budget.
- **Financement** :
  - mensualité (capital, taux d'intérêt et durée paramétrables, assurance
    emprunteur incluse) ;
  - taux d'endettement français avec repère au plafond HCSF de 35 % ;
  - reste à vivre mensuel estimé ;
  - comparateur de scénarios (plusieurs durées × plusieurs taux) avec graphique.
- **Revente / plus-value** :
  - calcul de la plus-value brute et nette ;
  - fiscalité simplifiée (exonération résidence principale, ou abattements
    pour durée de détention + prélèvements sociaux + surtaxe > 50k€ pour un
    bien secondaire/locatif) ;
  - ROI estimé par poste de travaux.
- **Tableau de bord** : vue d'ensemble, répartition des coûts, avancement des
  devis, checklist d'idées à ne pas oublier.

Les données sont stockées localement dans un fichier SQLite
(`immo_projet.db`), y compris les PDF (en pièce jointe téléchargeable).

## Installation locale

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Déploiement sur Streamlit Community Cloud (gratuit)

1. Pousse ce dossier sur un dépôt GitHub.
2. Va sur [share.streamlit.io](https://share.streamlit.io), connecte ton
   compte GitHub.
3. Sélectionne le dépôt, la branche, et `app.py` comme fichier principal.
4. Déploie.

⚠️ **Important si tu utilises Streamlit Community Cloud** : le système de
fichiers n'est **pas persistant**. Après une période d'inactivité, l'app peut
redémarrer dans un conteneur vide et perdre tes données (projets, devis, PDF).

L'application intègre maintenant une **sauvegarde manuelle**, dans la barre
latérale :
1. Avant de quitter, clique sur **"⬇️ Télécharger ma sauvegarde"** et garde ce
   fichier `.db` en lieu sûr (mail à toi-même, Google Drive, etc.).
2. À ta prochaine visite, si l'app semble vide, utilise
   **"⬆️ Restaurer une sauvegarde"** pour réimporter ce fichier.

Pour ne plus jamais avoir à y penser, la vraie solution est de brancher une
base de données en ligne (ex. Supabase) — dis-le moi si tu veux que je fasse
cette migration.

## Avertissement

Les calculs de taux d'endettement, de fiscalité sur la plus-value et de coût
du crédit sont **indicatifs**. Ils ne remplacent pas l'avis d'un courtier,
d'une banque, d'un notaire ou d'un conseiller fiscal.

## Idées d'évolutions possibles

- Export du dossier de financement en PDF/Excel pour le présenter à une banque.
- Timeline / Gantt des travaux.
- Alertes automatiques en cas de dépassement de budget par catégorie.
- Comparaison multi-projets (plusieurs biens visés en parallèle).
- Import de plusieurs devis en une fois (extraction par lot).
- Champ "cours du m²" du secteur pour comparer le prix d'achat au marché local.# Gestionnaire d'Achat Immobilier & Travaux 🏠

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
