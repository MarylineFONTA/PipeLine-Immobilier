import re
import json
from pathlib import Path
import scrapy
from scrapy.crawler import CrawlerProcess
from scrapy.http import Request

START_URLS = [
    "https://seloger.com",
]

#### essai3


SELECTORS = {
    # Sélecteurs CSS/XPath pour parcourir les cartes d'annonces
    "card": {
        "container": "article.listing-card",  # .card-ou-équivalent
        "link": "a::attr(href)",
    },
    # Sélecteurs dans la page détail d'une annonce
    "detail": {
        "title": "h1::text",
        "price": ".price::text",
        "surface": ".area::text",
        "rooms": ".rooms::text",
        "city": ".city::text",
        "postal_code": ".postal::text",

    },
}

# Helpers de nettoyage léger
PRICE_RE = re.compile(r"[\d\s\u202f\.] +")
SURFACE_RE = re.compile(r"([\d\.,]+)")
POSTAL_RE = re.compile(r"\b(\d{5})\b")

class AnnoncesSpider(scrapy.Spider):
    name = "annonces"
    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "USER_AGENT": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "DOWNLOAD_DELAY": 1.0,  # bienveillant
        "FEEDS": {
            "data/raw_data.json": {
                "format": "json",
                "encoding": "utf8",
                "overwrite": True,
                "indent": 2,
            }
        },
    }

    def start_requests(self):
        for url in START_URLS:
            yield Request(url, callback=self.parse_list)

    def parse_list(self, response):
        card_sel = SELECTORS["card"]["container"]
        for card in response.css(card_sel):
            link = card.css(SELECTORS["card"]["link"]).get()
            if link:
                yield response.follow(link, callback=self.parse_detail)

        # Pagination (facultatif) — désactivée par défaut pour limiter le volume
        # next_page = response.css("a.next::attr(href)").get()
        # if next_page:
        #     yield response.follow(next_page, callback=self.parse_list)

    def parse_detail(self, response):
        dsel = SELECTORS["detail"]
        def css_text(q):
            v = response.css(q).get()
            return v.strip() if v else None

        title = css_text(dsel["title"]) if dsel.get("title") else None
        price = css_text(dsel["price"]) if dsel.get("price") else None
        surface = css_text(dsel["surface"]) if dsel.get("surface") else None
        rooms = css_text(dsel["rooms"]) if dsel.get("rooms") else None
        city = css_text(dsel["city"]) if dsel.get("city") else None
        postal_code = css_text(dsel["postal_code"]) if dsel.get("postal_code") else None
        lat = css_text(dsel.get("lat", "")) if dsel.get("lat") else None
        lon = css_text(dsel.get("lon", "")) if dsel.get("lon") else None

        yield {
            "url": response.url,
            "title": title,
            "price_raw": price,
            "surface_raw": surface,
            "rooms_raw": rooms,
            "city": city,
            "postal_code_raw": postal_code,
            "lat": lat,
            "lon": lon,
        }


if __name__ == "__main__":
    Path("data").mkdir(exist_ok=True)
    process = CrawlerProcess()
    process.crawl(AnnoncesSpider)
    process.start()