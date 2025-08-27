# app.py
import re
from functools import lru_cache

import pandas as pd
import streamlit as st
import csv
import io
import requests

# ---------- CONFIG ----------
st.set_page_config(page_title="Immo Dashboard", layout="wide")

DEFAULT_CSV_URL = "https://raw.githubusercontent.com/MarylineFONTA/PipeLine-Immobilier/refs/heads/main/data/cleaned_data.csv"


# ---------- UTILS ----------
@st.cache_data(show_spinner=True, ttl=600)
def load_csv(url: str) -> pd.DataFrame:
    # Convertir URL GitHub "blob" -> "raw"
    if url.startswith("http") and "github.com" in url and "/blob/" in url:
        url = url.replace("https://github.com/", "https://raw.githubusercontent.com/").replace("/blob/", "/")

    # Récupérer le contenu (pour détecter une éventuelle 1re ligne 'sep=;')
    if url.startswith("http"):
        text = requests.get(url, timeout=30).text
    else:
        with open(url, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

    # Sauter la ligne 'sep=;' éventuelle
    lines = text.splitlines()
    if lines and lines[0].strip().lower().startswith("sep="):
        text = "\n".join(lines[1:])

    # Lecture robuste en supposant que ton pipeline écrit avec ';' et des guillemets "
    buf = io.StringIO(text)
    return pd.read_csv(
        buf,
        sep=";",
        engine="python",
        encoding="utf-8",
        quotechar='"',
        quoting=csv.QUOTE_MINIMAL,
        on_bad_lines="error",  # mets "warn" pour localiser si besoin
    )

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    # Harmonise les noms de colonnes usuels
    cols = {c.lower(): c for c in df.columns}
    rename = {}

    def has(*names): return next((cols[n] for n in names if n in cols), None)

    c_price_eur   = has("prix_eur", "price_eur")
    c_surface_m2 = has( "surface_m2", "surface_m2 (m2)")
    c_addr    = has("address", "adresse", "location")
    c_cp      = has("postal_code", "cp", "code_postal")
    c_lat     = has("lat", "latitude", "y")
    c_lon     = has("lon", "lng", "longitude", "x")
    c_url     = has("url", "lien")

    if c_price_eur:   rename[c_price_eur]   = "price_eur"
    if c_surface_m2: rename[c_surface_m2] = "surface_m2"
    if c_addr:    rename[c_addr]    = "address"
    if c_cp:      rename[c_cp]      = "postal_code"
    if c_lat:     rename[c_lat]     = "lat"
    if c_lon:     rename[c_lon]     = "lon"
    if c_url:     rename[c_url]     = "url"

    df = df.rename(columns=rename)

    # Types
    if "price_eur" in df:
        df["price_eur"] = pd.to_numeric(df["price_eur"], errors="coerce")
    if "surface_m2" in df:
        df["surface_m2"] = pd.to_numeric(df["surface_m2"], errors="coerce")

    # Ajouts utiles
    '''if {"price_eur", "surface_m2"}.issubset(df.columns):
     df["eur_m2"] = (df["price_eur"] / df["surface_m2"]).round(0)
  ''' 
    # Ville (simple extraction depuis l’adresse)
    if "address" in df and "city" not in df.columns:
        df["city"] = df["address"].fillna("").apply(extract_city)

    # Nettoyage de base
    if "url" in df.columns:
        df = df.drop_duplicates(subset=["url"])
    return df

def extract_city(addr: str) -> str | None:
    if not addr:
        return None
    # Exemples : "Paris 14ème (75014)" / "Lyon (69003)" / "Montpellier (34000)"
    m = re.search(r"([A-Za-zÀ-ÖØ-öø-ÿ'’\- ]+)\s*(?:\d+(?:er|e|ème)?)?\s*\(\d{5}\)", addr)
    if m: 
        return m.group(1).strip()
    # fallback très simple : avant la parenthèse
    m = re.search(r"([A-Za-zÀ-ÖØ-öø-ÿ'’\- ]+)\s*\(", addr)
    return m.group(1).strip() if m else None

@lru_cache(maxsize=2048)
def geocode_address(addr: str) -> tuple[float | None, float | None]:
    """Geocodage simple via Nominatim (optionnel). À activer par checkbox.
       NB: soumis à des limites de taux; préférer géocoder hors-ligne en batch."""
    try:
        from geopy.geocoders import Nominatim
        geolocator = Nominatim(user_agent="streamlit-immo-dashboard")
        loc = geolocator.geocode(addr, timeout=10)
        if loc:
            return (loc.latitude, loc.longitude)
    except Exception:
        pass
    return (None, None)

# ---------- SIDEBAR ----------
st.sidebar.header("Paramètres")
csv_url = st.sidebar.text_input("URL CSV (GitHub raw)", value=DEFAULT_CSV_URL, help="https://github.com/MarylineFONTA/PipeLine-Immobilier/blob/main/data/cleaned_data.csv")

df = load_csv(csv_url)

st.sidebar.markdown("### Filtres")
price_eur_min, price_eur_max = (
    int(df["price_eur"].min()) if "price_eur" in df and df["price_eur"].notna().any() else 0,
    int(df["price_eur"].max()) if "price_eur" in df and df["price_eur"].notna().any() else 1_000_000,
)
surface_m2_min, surface_m2_max = (
    int(df["surface_m2"].min()) if "surface_m2" in df and df["surface_m2"].notna().any() else 0,
    int(df["surface_m2"].max()) if "surface_m2" in df and df["surface_m2"].notna().any() else 200,
)

price_eur_sel = st.sidebar.slider("Prix (€)", min_value=price_eur_min, max_value=price_eur_max,
                              value=(price_eur_min, price_eur_max), step=max(1000, (price_eur_max-price_eur_min)//100 or 1))
surface_m2_sel = st.sidebar.slider("Surface (m²)", min_value=surface_m2_min, max_value=surface_m2_max,
                                value=(surface_m2_min, surface_m2_max), step=1)

cities = sorted([c for c in df.get("city", pd.Series([])).dropna().unique().tolist()])
city_sel = st.sidebar.multiselect("Ville", cities, default=[])

q = st.sidebar.text_input("Recherche texte (dans l’adresse)", value="")

do_geocode = st.sidebar.checkbox("Géocoder les lignes sans lat/lon (Nominatim)", value=False,
                                 help="À utiliser avec parcimonie (quotas). Le résultat est mis en cache en mémoire.")

# ---------- MAIN ----------
st.title("🏠 Tableau de bord immobilier")

# KPIs en haut
left, mid, right = st.columns(3)
left.metric("Annonces (total)", len(df))
if "price_eur" in df:
    mid.metric("Prix moyen (global)", f"{int(df['price_eur'].mean(skipna=True)):,} €".replace(",", " "))
if {"price_eur", "surface_m2"}.issubset(df.columns):
    right.metric("€/m² moyen (global)", f"{int(df['price_per_m2'].mean(skipna=True)):,} €".replace(",", " "))

# Filtres
mask = pd.Series(True, index=df.index)
if "price_eur" in df:
    mask &= df["price_eur"].between(price_eur_sel[0], price_eur_sel[1], inclusive="both")
if "surface_m2" in df:
    mask &= df["surface_m2"].between(surface_m2_sel[0], surface_m2_sel[1], inclusive="both")
if city_sel and "city" in df:
    mask &= df["city"].isin(city_sel)
if q:
    if "address" in df:
        mask &= df["address"].str.contains(q, case=False, na=False)
    elif "city" in df:
        mask &= df["city"].str.contains(q, case=False, na=False)

dff = df.loc[mask].copy()

# KPIs filtrés
st.subheader("Résultats filtrés")
k1, k2, k3 = st.columns(3)
k1.metric("Annonces retenues", len(dff))
if "price_eur" in dff and len(dff):
    k2.metric("Prix moyen (filtré)", f"{int(dff['price_eur'].mean(skipna=True)):,} €".replace(",", " "))
if {"price_eur", "surface_m2"}.issubset(dff.columns) and len(dff):
    k3.metric("€/m² moyen (filtré)", f"{int(dff['price_per_m2'].mean(skipna=True)):,} €".replace(",", " "))

# Histogramme des prix
if "price_eur" in dff and dff["price_eur"].notna().any():
    st.markdown("### Histogramme des prix")
    # bins automatiques ~ racine(n)
    bins = max(5, int(len(dff.dropna(subset=["price_eur"])) ** 0.5))
    hist, edges = pd.cut(dff["price_eur"], bins=bins, retbins=True, include_lowest=True)
    chart_df = hist.value_counts().sort_index().to_frame("count")
    chart_df.index = [f"{int(edges[i]):,} – {int(edges[i+1]):,} €".replace(",", " ") for i in range(len(edges)-1)]
    st.bar_chart(chart_df)

# Carte (si lat/lon)
if {"lat", "lon"}.issubset(dff.columns) and dff[["lat","lon"]].notna().all(axis=1).any():
    st.markdown("### Carte")
    st.map(dff[["lat", "lon"]].dropna())
elif do_geocode and "address" in dff:
    # geocode on the fly (simple/caché)
    st.markdown("### Carte (géocodage à la volée)")
    lat, lon = [], []
    for addr in dff["address"].fillna(""):
        y, x = geocode_address(addr)  # (lat, lon)
        lat.append(y); lon.append(x)
    dff["_lat"], dff["_lon"] = lat, lon

    # Column renaming here
    dff = dff.rename(columns={'_lat': 'latitude', '_lon': 'longitude'})

    # Call st.map with the renamed columns
    st.map(dff[["latitude", "longitude"]].dropna())
    dff = dff.drop(columns=["latitude", "longitude"], errors="ignore")
    
    #st.map(dff[["_lat", "_lon"]].dropna())
    #dff = dff.drop(columns=["_lat", "_lon"], errors="ignore")

# Tableau
st.markdown("### Données filtrées")
# Configuration des colonnes (URL cliquable si possible)
col_config = {}
if "url" in dff.columns:
    try:
        col_config["url"] = st.column_config.LinkColumn("Lien", display_text="Annonce")
    except Exception:
        pass

st.dataframe(
    dff.sort_values(by=["price_eur"], ascending=True, na_position="last") if "price_eur" in dff else dff,
    use_container_width=True,
    column_config=col_config or None,
)

st.caption("Astuce : mets à jour l’URL du CSV dans la barre latérale pour pointer sur ta dernière donnée.")
