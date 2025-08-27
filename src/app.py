# src/app.py
from __future__ import annotations

import pandas as pd
import streamlit as st
import altair as alt
import numpy as np

# Pour géolocaliser rapidement via les codes postaux (centroïdes)
# pip install pgeocode
import pgeocode


# 👉 REMPLACE l’URL ci-dessous par le lien "raw" de ton CSV sur GitHub
GITHUB_CSV_URL = "https://raw.githubusercontent.com/<user>/<repo>/<branch>/data/seloger_tp.csv"


st.set_page_config(page_title="Tableau de bord Immobilier", layout="wide")


@st.cache_data(show_spinner=False)
def load_data(csv_url: str) -> pd.DataFrame:
    # Lecture robuste (délimiteur auto, ; ou ,)
    df = pd.read_csv(csv_url, sep=None, engine="python", encoding="utf-8")
    # Normalisation types
    for c in ["price_eur", "surface_m2", "price_per_m2"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ["rooms", "floor", "year_built"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")

    # Si price_per_m2 absent ou incomplet, on le calcule
    if "price_per_m2" not in df.columns:
        df["price_per_m2"] = np.where(
            (df.get("price_eur").notna()) & (df.get("surface_m2").notna()) & (df["surface_m2"] > 0),
            (df["price_eur"] / df["surface_m2"]).round(2),
            np.nan,
        )
    return df


@st.cache_data(show_spinner=False)
def add_lat_lon_from_postcode(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ajoute des colonnes lat/lon à partir de postal_code (France) via pgeocode.
    Utilise les centroïdes de code postal -> bonne approximation pour la carte.
    """
    if "postal_code" not in df.columns:
        return df

    # Harmonise les CP en chaîne 5 caractères
    pc = df["postal_code"].astype(str).str.extract(r"(\d{5})", expand=False)
    df = df.copy()
    df["postal_code_norm"] = pc

    unique_pc = df["postal_code_norm"].dropna().unique().tolist()
    if not unique_pc:
        return df

    nomi = pgeocode.Nominatim("fr")
    look = nomi


