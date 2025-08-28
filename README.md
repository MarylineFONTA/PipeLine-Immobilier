# 🏡 Pipeline de Données : Analyse du Marché Immobilier

Ce projet a pour but de construire un pipeline de données automatisé pour scraper des annonces immobilières, les nettoyer, et les visualiser via un tableau de bord interactif. L'objectif principal est de fournir une solution qui se met à jour quotidiennement de manière autonome.

-----

## 🏗️ Architecture du Projet

Le pipeline se compose de trois étapes principales :

  * **1. Web Scraping 🕷️**

      * Le **spider Scrapy** (`spider.py`) est utilisé pour extraire les informations clés (prix, surface, etc.) à partir d'un site d'annonces. Les données brutes sont exportées dans un fichier JSON.

  * **2. Ingénierie des Données 🧹**

      * Un script Python (`cleaner.py`) utilise la librairie `pandas` pour nettoyer et structurer les données du fichier JSON. Il gère la conversion des types de données et les valeurs manquantes, et calcule des métriques comme le prix au $m^2$. Le résultat est sauvegardé dans un fichier CSV (`cleaned_data.csv`), prêt à être utilisé.

  * **3. Automatisation CI/CD 🤖**

      * Un pipeline **GitHub Actions** (`.github/workflows/main.yml`) déclenche l'exécution du spider et du script de nettoyage de manière quotidienne. Le workflow commite et met à jour le fichier `cleaned_data.csv` dans le dépôt GitHub.

  * **4. Tableau de bord interactif 📊**

      * Une application web, développée avec **Streamlit** (`app.py`), lit les données directement depuis le fichier `cleaned_data.csv` du dépôt. Elle permet une exploration interactive des données via des filtres et des visualisations.

-----

## 📂 Structure des Fichiers

  * `src/`
      * `spider.py`: Le spider Scrapy pour la collecte de données brutes.
      * `cleaner.py`: Le script de nettoyage et de transformation des données.
  * `data/`
      * `raw_data.json`: Fichier JSON contenant les données brutes extraites par Scrapy.
      * `cleaned_data.csv`: Le fichier de données final, nettoyé et structuré, utilisé par l'application Streamlit.
  * `.github/workflows/`
      * `main.yml`: Le script GitHub Actions qui orchestre le pipeline CI/CD.
  * `app.py`: Le code de l'application Streamlit pour la visualisation.

-----

## ▶️ Comment lancer le projet en local

1.  **Cloner le dépôt** :

    ```bash
    git clone https://github.com/votre-utilisateur/votre-repo.git
    cd votre-repo
    ```

2.  **Installer les dépendances** :

    ```bash
    pip install -r requirements.txt
    ```

3.  **Exécuter le pipeline manuellement** :

    ```bash
    python src/spider.py
    python src/cleaner.py
    ```

4.  **Lancer le tableau de bord Streamlit** :

    ```bash
    streamlit run app.py
    ```

-----
