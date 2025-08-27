import re, json
from pathlib import Path
import scrapy
from scrapy.crawler import CrawlerProcess

# ----------------- 10 URLs d'annonces -----------------
START_URLS = [
    "https://www.seloger.com/annonces/achat/appartement/paris-5eme-75/saint-victor/248383921.htm",
    "https://www.seloger.com/annonces/achat/appartement/paris-14eme-75/248397275.htm",
    "https://www.seloger.com/annonces/achat/appartement/paris-7eme-75/248601869.htm",
    "https://www.seloger.com/annonces/achat/appartement/paris-14eme-75/raspail-montparnasse/248533527.htm",
    "https://www.seloger.com/annonces/achat/appartement/paris-19eme-75/manin-jaures/248666645.htm",
    "https://www.seloger.com/annonces/achat/appartement/paris-14eme-75/jean-moulin-porte-d-orleans/248484735.htm",
    "https://www.seloger.com/annonces/achat/appartement/paris-18eme-75/grandes-carrieres-clichy/248528065.htm",
    "https://www.seloger.com/annonces/achat/appartement/paris-7eme-75/ecole-militaire/248571179.htm",
    "https://www.seloger.com/annonces/achat/appartement/paris-14eme-75/pernety/248251445.htm",
    "https://www.seloger.com/annonces/achat/appartement/paris-13eme-75/nationale-deux-moulins/241499915.htm",
]

# ----------------- regex utilitaires -----------------

# -- repère le "bord" après l'étage (gère "Étage 1/6" et "5ème étage", et ignore "étages")
FLOOR_MARK = re.compile(
    r"(?:\b(?:[ÉE]tage|Etage)\b\s*\d+(?:/\d+)?|\b\d+\s*(?:er|e|ème|ᵉ)?\s*étage(?!s)|\b(?:RDC|rez[- ]de[- ]chauss[eé]e)\b)",
    re.I,
)

PARIS_ADDR_RE   = re.compile(r"[A-ZÀ-ÖØ-öø-ÿ][\w’'\- ]+,\s*Paris\s*\d+(?:er|e|ème)?\s*\(\d{5}\)")
GENERIC_ADDR_RE = re.compile(r"[A-ZÀ-ÖØ-öø-ÿ][\w’'\- ]+,\s*[A-ZÀ-ÖØ-öø-ÿ][\w’'\- ]+\s*\(\d{5}\)")
EURO_RE   = re.compile(r"(\d[\d\u00A0\u202f\s.,]{3,})\s*€")  # nb + € (prendrons la max)
SURF_RE   = re.compile(r"(\d+[.,]?\d*)\s*(m²|m2)", re.I)
ROOMS_RE  = re.compile(r"(\d+)\s*pi[eè]ces?", re.I)
ROOMS_TRE = re.compile(r"\bT\s?(\d)\b", re.I)
FLOOR_ONE = re.compile(r"\b(?:[ÉE]tage|Etage)\s*(\d+)(?:/\d+)?\b")  # "Étage 1/6" -> 1
FLOOR_TWO = re.compile(r"(?:\bau\s*)?(\d+)\s*(?:er|e|ème|ᵉ)?\s*étage(?!s)", re.I)  # évite "étages"
RDC_RE    = re.compile(r"\b(?:rdc|rez[- ]de[- ]chauss[eé]e)\b", re.I)
CP_RE     = re.compile(r"\b(\d{5})\b")
# DPE lettre dans le texte (fallback)
DPE_LETTER_RE = re.compile(r"\b([A-G])\b")
DPE_NEAR_RE   = re.compile(r"(?:DPE|classe\s+énergie|diagnostic de performance énergétique)[^A-G]{0,40}\b([A-G])\b", re.I)
GES_NEAR_RE = re.compile(r"(?:GES|gaz\s+à\s+effet\s+de\s+serre|gaz\s+a\s+effet\s+de\s+serre)[^A-G]{0,40}\b([A-G])\b", re.I)
# 4 chiffres entre 1000 et 2099 pour l'année de construction
YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")

def to_float_fr(s):
    if s is None: return None
    if isinstance(s, (int, float)): return float(s)
    s = str(s).replace("\u202f","").replace("\u00A0","").replace(" ","")
    s = s.replace(".", "").replace(",", ".")
    try: return float(s)
    except: return None

def first_ld_listing(ld_objs):
    ok = {"RealEstateListing","Apartment","House","SingleFamilyResidence","Product","Offer","Appartement","Maison"}
    if isinstance(ld_objs, dict): ld_objs = [ld_objs]
    for ld in ld_objs or []:
        if isinstance(ld, dict) and (ld.get("@type") in ok or "offers" in ld or "address" in ld):
            return ld
    return None

def clean_address(s: str|None) -> str|None:
    if not s: return s
    s = s.replace("•", " ").replace("  ", " ").strip(" ,•")
    s = re.sub(r"Calculer un temps de trajet.*", "", s, flags=re.I)
    s = re.sub(r"\s{2,}", " ", s).strip(" ,•")
    return s or None

def _norm(s: str|None) -> str|None:
    if not s: return None
    s = s.replace("\u202f"," ").replace("\u00A0"," ")
    return s.strip()

def _pick_letter(txt: str | None) -> str | None:
    if not txt: return None
    L = _norm(txt).upper()
    return L if L in list("ABCDEFG") else None

def extract_dpe_and_ges_letters(response):
    """
    Retourne un tuple (dpe_letter, ges_letter).
    Stratégie:
      1) Parcourt chaque jauge [data-testid='cdp-preview-scale'] et cherche
         la lettre sur l'élément [data-testid='cdp-preview-scale-highlighted'].
      2) Essaie de déduire le libellé de la jauge via le heading précédent (DPE vs GES).
      3) Si ambigu et qu'on a 2 lettres, on attribue la 1ère au DPE, la 2ème au GES.
      4) Fallback: cherche "DPE: X" / "GES: Y" dans le texte global.
    """
    dpe, ges = None, None

    scales = response.css("[data-testid='cdp-preview-scale']")
    found_letters = []

    for sc in scales:
        letter = _pick_letter(sc.css("[data-testid='cdp-preview-scale-highlighted']::text").get())
        if not letter:
            # autre tentative : le seul enfant aria-hidden="false"
            letter = _pick_letter(sc.css("[aria-hidden='false']::text").get())
        if not letter:
            continue

        # Tente d’identifier si c’est la jauge DPE ou GES via le heading précédent
        label_txt = " ".join(sc.xpath("(preceding::h2|preceding::h3)[1]//text()").getall()).lower()
        if any(k in label_txt for k in ["ges", "gaz à effet de serre", "gaz a effet de serre"]):
            ges = ges or letter
        elif any(k in label_txt for k in ["dpe", "classe énergie", "classe energie"]):
            dpe = dpe or letter
        else:
            found_letters.append(letter)

    # Si on a 2 lettres au total et pas d’étiquetage clair : 1ère = DPE, 2ème = GES
    if (dpe is None or ges is None) and len(scales) >= 2:
        # Récupère toutes les lettres dans l’ordre d’apparition
        all_letters = [
            _pick_letter(x) for x in
            response.css("[data-testid='cdp-preview-scale'] [data-testid='cdp-preview-scale-highlighted']::text").getall()
        ]
        all_letters = [x for x in all_letters if x]

        if len(all_letters) >= 2:
            if dpe is None: dpe = all_letters[0]
            if ges is None: ges = all_letters[1]

    # Fallback texte global si encore manquant
    if dpe is None or ges is None:
        full = " ".join(response.css("body *::text").getall())
        if dpe is None:
            m = DPE_NEAR_RE.search(full)
            if m: dpe = m.group(1).upper()
        if ges is None:
            m = GES_NEAR_RE.search(full)
            if m: ges = m.group(1).upper()

    return dpe, ges
def _to_year_value(s):
    if s is None:
        return None
    m = YEAR_RE.search(str(s))
    if not m:
        return None
    y = int(m.group(1))
    return y if 1000 <= y <= 2100 else None

def extract_year_built(response, ld_obj=None):
    """
    Retourne l'année de construction (int) si trouvée, sinon None.
    Priorités :
      1) JSON-LD (dateBuilt / yearBuilt / additionalProperty)
      2) data-testid='cdp-energy-features.yearOfConstruction'
      3) Libellé 'Année de construction' dans la page
      4) Texte global
    """

    # --- 1) JSON-LD ---
    if isinstance(ld_obj, dict):
        # champs simples
        for k in ("dateBuilt", "yearBuilt", "constructionYear"):
            y = _to_year_value(ld_obj.get(k))
            if y:
                return y
        # parfois dans additionalProperty
        ap = ld_obj.get("additionalProperty")
        if isinstance(ap, dict):
            ap = [ap]
        if isinstance(ap, list):
            for p in ap:
                try:
                    name = (p.get("name") or p.get("propertyID") or "").lower()
                    val = p.get("value") or p.get("valueReference")
                    if any(w in name for w in ("construction", "année", "annee", "year")):
                        y = _to_year_value(val)
                        if y:
                            return y
                except Exception:
                    continue

    # --- 2) Sélecteur data-testid (ton HTML) ---
    txt = response.css("[data-testid='cdp-energy-features.yearOfConstruction']::text").get()
    y = _to_year_value(txt)
    if y:
        return y

    # --- 3) Libellé voisin 'Année de construction' ---
    # exemple : <span>Année de construction</span><span>1703</span>
    txt = response.xpath("//*[contains(normalize-space(.), 'Année de construction')]/following::span[1]/text()").get()
    y = _to_year_value(txt)
    if y:
        return y

    # --- 4) Texte global (fallback ultime) ---
    scope = " ".join(response.css("[data-testid^='cdp-energy-features'] ::text").getall())
    y = _to_year_value(scope)
    if y:
        return y

    full = " ".join(response.css("body *::text").getall())
    return _to_year_value(full)

class SeLogerSelectorsTP(scrapy.Spider):
    name = "raw_data.json"
    custom_settings = {
        "ROBOTSTXT_OBEY": True,   # conforme : on visite seulement des fiches
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS": 1,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 1,
        "FEEDS": {"data/raw_data.json": {"format":"json","encoding":"utf8","overwrite":True,"indent":2}},
        "USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    }

    # Scrapy 2.13+ : start()
    async def start(self):
        for url in START_URLS:
            yield scrapy.Request(url, callback=self.parse_detail)

    # def start_requests(self):  # décommente si Scrapy < 2.13
    #     for url in START_URLS:
    #         yield scrapy.Request(url, callback=self.parse_detail)

    def parse_detail(self, response):
        item = {
            "url": response.url,
            "title": None,
            "price_eur": None,
            "surface_m2": None,
            "rooms": None,
            "floor": None,
            "address": None,
            "postal_code": None,
            "description": None,
            "dpe_letter": None, 
            "ges_letter": None, 
            "year_built": None, 
        }

        # -------- 1) JSON-LD (sélecteur) --------
        lds = []
        for raw in response.xpath("//script[@type='application/ld+json']/text()").getall():
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict) and "@graph" in obj:
                    lds.extend(obj["@graph"])
                else:
                    lds.append(obj)
            except: pass
        ld = first_ld_listing(lds)

        if ld:
            # titre
            item["title"] = ld.get("name") or ld.get("title")

            # prix
            offers = ld.get("offers")
            if isinstance(offers, list) and offers:
                offers = offers[0]
            if isinstance(offers, dict):
                item["price_eur"] = to_float_fr(offers.get("price"))

            # surface
            floorSize = ld.get("floorSize")
            if isinstance(floorSize, dict):
                item["surface_m2"] = to_float_fr(floorSize.get("value"))

            # pièces
            rooms = ld.get("numberOfRooms") or ld.get("numberOfRoomsTotal")
            if isinstance(rooms, (int,float,str)):
                try: item["rooms"] = int(float(rooms))
                except: pass

            # adresse
            addr = ld.get("address") or {}
            if isinstance(addr, dict):
                parts = [addr.get("streetAddress"), addr.get("postalCode"), addr.get("addressLocality")]
                item["address"] = clean_address(", ".join([p for p in parts if p]))
                m = CP_RE.search(addr.get("postalCode") or "")
                item["postal_code"] = m.group(1) if m else None

            # étage (si exposé)
            item["floor"] = ld.get("floorLevel") or ld.get("floor")

            # description
            item["description"] = ld.get("description")

        # -------- 2) Fallbacks (sélecteurs + regex) --------
        # titre : og:title > h1
        if item["title"] is None:
            item["title"] = response.css("meta[property='og:title']::attr(content)").get()
        if item["title"] is None:
            item["title"] = response.css("h1::text").get() or response.xpath("//h1//text()").get()

        full = " ".join(response.css("body *::text").getall())

        # prix : meta itemprop/price > regex (plus grande valeur avant €)
        if item["price_eur"] is None:
            meta_price = (
                response.css("meta[itemprop='price']::attr(content)").get() or
                response.css("meta[property='product:price:amount']::attr(content)").get() or
                response.css("meta[name='price']::attr(content)").get()
            )
            if meta_price:
                item["price_eur"] = to_float_fr(meta_price)
            else:
                nums = [to_float_fr(m) for m in EURO_RE.findall(full)]
                nums = [n for n in nums if n]
                if nums:
                    item["price_eur"] = max(nums)  # évite surface/charges

        # surface
        if item["surface_m2"] is None:
            m = SURF_RE.search(full)
            if m:
                item["surface_m2"] = to_float_fr(m.group(1))

        # pièces
        if item["rooms"] is None:
            m = ROOMS_RE.search(full) or ROOMS_TRE.search(full)
            if m:
                try: item["rooms"] = int(m.group(1))
                except: pass

        # étage
        if item["floor"] is None:
            if RDC_RE.search(full):
                item["floor"] = 0
            else:
                m = FLOOR_ONE.search(full) or FLOOR_TWO.search(full)
                if m:
                    item["floor"] = int(m.group(1))

        # adresse + CP (si JSON-LD absent)
        # --- Adresse depuis le HTML (sans JSON-LD) ---
        if item.get("address") is None:
            # 1) Essai direct si tu connais la classe (peut changer)
            addr = response.css("span.css-1d82754::text").get()

            # 2) Plus robuste : balayer tous les <span> et matcher le motif
            if not addr:
                # priorité à Paris : "Quartier, Paris 14ème (75014)"
                addr = response.css("span::text").re_first(PARIS_ADDR_RE)
            if not addr:
                # sinon "Quartier, Ville (750xx)"
                addr = response.css("span::text").re_first(GENERIC_ADDR_RE)

            # 3) Variante XPath si tu préfères :
            # if not addr:
            #     addr = response.xpath("//span/text()").re_first(PARIS_ADDR_RE.pattern) \
            #            or response.xpath("//span/text()").re_first(GENERIC_ADDR_RE.pattern)

            item["address"] = clean_address(addr)

        # Compléter le code postal si manquant
        if item.get("address") and not item.get("postal_code"):
            m = CP_RE.search(item["address"])
            if m:
                item["postal_code"] = m.group(1)


        # description : og:description > meta description > plus long <p>
        if item["description"] is None:
            item["description"] = (
                response.css("div.css-z0zigl.DescriptionTexts::text").get()
            )
        if item["description"] is None:
            paras = [p.strip() for p in response.css("p::text").getall()]
            paras = [p for p in paras if len(p) > 80 and "Calculer un temps de trajet" not in p]
            if paras:
                item["description"] = max(paras, key=len)

       # ---- DPE & GES ----
        if item["dpe_letter"] is None or item["ges_letter"] is None:
            dpe, ges = extract_dpe_and_ges_letters(response)
            item["dpe_letter"] = item["dpe_letter"] or dpe
            item["ges_letter"] = item["ges_letter"] or ges

        # Année de construction
        if item["year_built"] is None:
            item["year_built"] = extract_year_built(response, ld_obj=ld)


        yield item


if __name__ == "__main__":
    Path("data").mkdir(exist_ok=True)
    process = CrawlerProcess()
    process.crawl(SeLogerSelectorsTP)
    process.start()
