import re, json
from urllib.parse import urljoin, urlparse
from pathlib import Path
import scrapy
from scrapy.crawler import CrawlerProcess
from scrapy.exceptions import CloseSpider

# ----------------- Config -----------------
SEARCH_URL  = "https://www.seloger.com/immobilier/achat/immo-paris-75/"
OUTPUT_PATH = Path("data/raw_data.json")
MAX_NEW     = 10        # combien de NOUVELLES annonces (ID inédits) on veut
MAX_PAGES   = 25       # garde-fou anti-boucle (facultatif)

# ----------------- Regex utilitaires (inchangées / abrégées) -----------------
PARIS_ADDR_RE   = re.compile(r"[A-ZÀ-ÖØ-öø-ÿ][\w’'\- ]+,\s*Paris\s*\d+(?:er|e|ème)?\s*\(\d{5}\)")
GENERIC_ADDR_RE = re.compile(r"[A-ZÀ-ÖØ-öø-ÿ][\w’'\- ]+,\s*[A-ZÀ-ÖØ-öø-ÿ][\w’'\- ]+\s*\(\d{5}\)")
EURO_RE   = re.compile(r"(\d[\d\u00A0\u202f\s.,]{3,})\s*€")
SURF_RE   = re.compile(r"(\d+[.,]?\d*)\s*(m²|m2)", re.I)
ROOMS_RE  = re.compile(r"(\d+)\s*pi[eè]ces?", re.I)
ROOMS_TRE = re.compile(r"\bT\s?(\d)\b", re.I)
FLOOR_ONE = re.compile(r"\b(?:[ÉE]tage|Etage)\s*(\d+)(?:/\d+)?\b")
FLOOR_TWO = re.compile(r"(?:\bau\s*)?(\d+)\s*(?:er|e|ème|ᵉ)?\s*étage(?!s)", re.I)
RDC_RE    = re.compile(r"\b(?:rdc|rez[- ]de[- ]chauss[eé]e)\b", re.I)
CP_RE     = re.compile(r"\b(\d{5})\b")
DPE_NEAR_RE = re.compile(r"(?:DPE|classe\s+énergie|diagnostic de performance énergétique)[^A-G]{0,40}\b([A-G])\b", re.I)
GES_NEAR_RE = re.compile(r"(?:GES|gaz\s+à\s+effet\s+de\s+serre|gaz\s+a\s+effet\s+de\s+serre)[^A-G]{0,40}\b([A-G])\b", re.I)
YEAR_RE   = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")

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

def clean_address(s):
    if not s: return s
    s = s.replace("•"," ").replace("  "," ").strip(" ,•")
    s = re.sub(r"Calculer un temps de trajet.*", "", s, flags=re.I)
    s = re.sub(r"\s{2,}", " ", s).strip(" ,•")
    return s or None

def _pick_letter(txt):
    if not txt: return None
    L = txt.replace("\u202f"," ").replace("\u00A0"," ").strip().upper()
    return L if L in "ABCDEFG" else None

def extract_dpe_and_ges_letters(response):
    dpe, ges = None, None
    scales = response.css("[data-testid='cdp-preview-scale']")
    for sc in scales:
        letter = _pick_letter(sc.css("[data-testid='cdp-preview-scale-highlighted']::text").get()) \
              or _pick_letter(sc.css("[aria-hidden='false']::text").get())
        if not letter: continue
        label_txt = " ".join(sc.xpath("(preceding::h2|preceding::h3)[1]//text()").getall()).lower()
        if any(k in label_txt for k in ["ges","gaz à effet de serre","gaz a effet de serre"]):
            ges = ges or letter
        elif any(k in label_txt for k in ["dpe","classe énergie","classe energie"]):
            dpe = dpe or letter
    if dpe is None or ges is None:
        full = " ".join(response.css("body *::text").getall())
        if dpe is None:
            m = DPE_NEAR_RE.search(full);  dpe = m.group(1).upper() if m else dpe
        if ges is None:
            m = GES_NEAR_RE.search(full);  ges = m.group(1).upper() if m else ges
    return dpe, ges

def _to_year_value(s):
    if s is None: return None
    m = YEAR_RE.search(str(s));  y = int(m.group(1)) if m else None
    return y if y and 1000 <= y <= 2100 else None

def extract_year_built(response, ld_obj=None):
    if isinstance(ld_obj, dict):
        for k in ("dateBuilt","yearBuilt","constructionYear"):
            y = _to_year_value(ld_obj.get(k));  
            if y: return y
        ap = ld_obj.get("additionalProperty")
        if isinstance(ap, dict): ap = [ap]
        if isinstance(ap, list):
            for p in ap:
                try:
                    name = (p.get("name") or p.get("propertyID") or "").lower()
                    val  = p.get("value") or p.get("valueReference")
                    if any(w in name for w in ("construction","année","annee","year")):
                        y = _to_year_value(val);  
                        if y: return y
                except: pass
    txt = response.css("[data-testid='cdp-energy-features.yearOfConstruction']::text").get()
    y = _to_year_value(txt);  0
    if y: return y
    txt = response.xpath("//*[contains(normalize-space(.), 'Année de construction')]/following::span[1]/text()").get()
    y = _to_year_value(txt);  0
    if y: return y
    scope = " ".join(response.css("[data-testid^='cdp-energy-features'] ::text").getall())
    y = _to_year_value(scope);  0
    if y: return y
    full = " ".join(response.css("body *::text").getall())
    return _to_year_value(full)

class SeLogerSelectorsTP(scrapy.Spider):
    name = "raw_data.json"
    allowed_domains = ["www.seloger.com","seloger.com"]
    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS": 1,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 1,
        "USER_AGENT" : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        #"USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Charger ce qui existe déjà
        self.items = []
        self.existing_ids = set()
        if OUTPUT_PATH.exists() and OUTPUT_PATH.stat().st_size > 0:
            try:
                data = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self.items.extend(data)
                    for it in data:
                        try: self.existing_ids.add(int(it.get("ID")))
                        except: pass
                self.logger.info(f"{len(self.items)} items chargés ({len(self.existing_ids)} IDs connus).")
            except Exception as e:
                self.logger.warning(f"Lecture {OUTPUT_PATH} impossible: {e}")

        # État du run
        self.run_seen_ids = set(self.existing_ids)   # pour ignorer doublons intra-run
        self.new_found    = 0
        self.pages_seen   = 0

    # Scrapy 2.13+
    async def start(self):
        yield scrapy.Request(SEARCH_URL, callback=self.parse_search, dont_filter=True)

    def parse_search(self, response):
        if self.new_found >= MAX_NEW:
            raise CloseSpider("quota_reached")

        self.pages_seen += 1
        if self.pages_seen > MAX_PAGES:
            raise CloseSpider("max_pages_guard")

        # Collecter des liens d'annonces
        candidates = []
        for href in response.css("a[href*='/annonces/']::attr(href)").getall():
            url = urljoin(response.url, href.split('#')[0])
            if "/annonces/achat/" in url and urlparse(url).netloc.endswith("seloger.com"):
                clean = url.split("?")[0].rstrip("/")
                candidates.append(clean)

        # Déclencher le parsing détail pour tous les candidats
        for u in dict.fromkeys(candidates):  # dédupe simple en conservant l'ordre
            # On ne connaît l'ID qu'après ouverture de la fiche → on tente
            yield scrapy.Request(u, callback=self.parse_detail, dont_filter=True)

        # Si on n’a pas encore le quota de nouveaux, continuer la pagination
        if self.new_found < MAX_NEW:
            next_url = (
                response.css("a[rel='next']::attr(href)").get() or
                response.css("a[aria-label*='Suivant' i]::attr(href)").get()
            )
            if next_url:
                yield scrapy.Request(urljoin(response.url, next_url), callback=self.parse_search, dont_filter=True)
            else:
                # plus de pages → on laisse le spider se fermer naturellement
                self.logger.info("Plus de pagination disponible.")

    def parse_detail(self, response):
        # Identifier l'ID ; si échec, on ignore
        try:
            id_val = int(response.url.rsplit('/', 1)[-1].split('?', 1)[0].split('#', 1)[0].split('.', 1)[0])
        except Exception:
            self.logger.debug(f"ID introuvable pour {response.url}")
            return

        # Déjà connu (dans le fichier ou déjà vu pendant ce run) → on saute
        if id_val in self.run_seen_ids:
            return

        # ---- À partir d’ici, c’est un NOUVEL ID → on extrait et ajoute ----
        item = {
            "url": response.url,
            "ID" : id_val,
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
            "property_type": None,
        }

        # 1) JSON-LD
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
            item["title"] = ld.get("name") or ld.get("title")
            offers = ld.get("offers")
            if isinstance(offers, list) and offers: offers = offers[0]
            if isinstance(offers, dict): item["price_eur"] = to_float_fr(offers.get("price"))
            floorSize = ld.get("floorSize")
            if isinstance(floorSize, dict): item["surface_m2"] = to_float_fr(floorSize.get("value"))
            rooms = ld.get("numberOfRooms") or ld.get("numberOfRoomsTotal")
            if isinstance(rooms, (int,float,str)):
                try: item["rooms"] = int(float(rooms))
                except: pass
            addr = ld.get("address") or {}
            if isinstance(addr, dict):
                parts = [addr.get("streetAddress"), addr.get("postalCode"), addr.get("addressLocality")]
                item["address"] = clean_address(", ".join([p for p in parts if p]))
                m = CP_RE.search(addr.get("postalCode") or "");  item["postal_code"] = m.group(1) if m else None
            item["floor"] = ld.get("floorLevel") or ld.get("floor")
            item["description"] = ld.get("description")
            if "/appartement/" in response.url.lower(): item["property_type"] = "appartement"
            elif "/maison/" in response.url.lower():   item["property_type"] = "maison"
            if not item.get("property_type"):
                ld_type = str(ld.get("@type", "")).lower()
                if "apartment" in ld_type or "appartement" in ld_type: item["property_type"] = "appartement"
                elif "house" in ld_type or "maison" in ld_type:        item["property_type"] = "maison"

        # 2) Fallbacks
        if item["title"] is None:
            item["title"] = response.css("meta[property='og:title']::attr(content)").get() \
                         or response.css("h1::text").get() \
                         or response.xpath("//h1//text()").get()
        full = " ".join(response.css("body *::text").getall())
        if item["price_eur"] is None:
            meta_price = (
                response.css("meta[itemprop='price']::attr(content)").get() or
                response.css("meta[property='product:price:amount']::attr(content)").get() or
                response.css("meta[name='price']::attr(content)").get()
            )
            if meta_price: item["price_eur"] = to_float_fr(meta_price)
            else:
                nums = [to_float_fr(m) for m in EURO_RE.findall(full)]
                nums = [n for n in nums if n]
                if nums: item["price_eur"] = max(nums)
        if item["surface_m2"] is None:
            m = SURF_RE.search(full);  item["surface_m2"] = to_float_fr(m.group(1)) if m else None
        if item["rooms"] is None:
            m = ROOMS_RE.search(full) or ROOMS_TRE.search(full)
            if m:
                try: item["rooms"] = int(m.group(1))
                except: pass
        if item["floor"] is None:
            if RDC_RE.search(full): item["floor"] = 0
            else:
                m = FLOOR_ONE.search(full) or FLOOR_TWO.search(full)
                if m: item["floor"] = int(m.group(1))
        if item.get("address") is None:
            addr = response.css("span.css-1d82754::text").get() \
                or response.css("span::text").re_first(PARIS_ADDR_RE) \
                or response.css("span::text").re_first(GENERIC_ADDR_RE)
            item["address"] = clean_address(addr)
        if item.get("address") and not item.get("postal_code"):
            m = CP_RE.search(item["address"]);  item["postal_code"] = m.group(1) if m else None
        if item["description"] is None:
            item["description"] = response.css("div.css-z0zigl.DescriptionTexts::text").get()
            if item["description"] is None:
                paras = [p.strip() for p in response.css("p::text").getall()]
                paras = [p for p in paras if len(p) > 80 and "Calculer un temps de trajet" not in p]
                if paras: item["description"] = max(paras, key=len)
        dpe, ges = extract_dpe_and_ges_letters(response)
        item["dpe_letter"] = item["dpe_letter"] or dpe
        item["ges_letter"] = item["ges_letter"] or ges
        if item["year_built"] is None:
            item["year_built"] = extract_year_built(response, ld_obj=ld)
        if not item.get("property_type"):
            page_text = full.lower()
            if "appartement" in page_text: item["property_type"] = "appartement"
            elif "maison" in page_text:     item["property_type"] = "maison"

        # Ajout et comptage
        self.items.append(item)
        self.run_seen_ids.add(id_val)
        self.new_found += 1

        # Si on a atteint le quota, on arrête net le spider
        if self.new_found >= MAX_NEW:
            self.crawler.engine.close_spider(self, "quota_reached")

    def closed(self, reason):
        # Fusion/écriture dédupliquée par ID
        Path("data").mkdir(exist_ok=True)
        unique = {}
        for it in self.items:
            try: unique[int(it.get("ID"))] = it
            except: pass
        data = list(unique.values())
        with OUTPUT_PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.logger.info(f"{len(data)} items écrits dans {OUTPUT_PATH} (fermeture: {reason})")

if __name__ == "__main__":
    Path("data").mkdir(exist_ok=True)
    process = CrawlerProcess()
    process.crawl(SeLogerSelectorsTP)
    process.start()
