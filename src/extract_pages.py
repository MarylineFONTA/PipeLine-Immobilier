import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import scrapy
from scrapy.exceptions import CloseSpider


def set_or_add_page_param(url: str, page: int) -> str:
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    q["page"] = [str(page)]
    new_query = urlencode(q, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


class SeLogerLinksSpider(scrapy.Spider):
    name = "seloger_links"
    allowed_domains = ["seloger.com", "www.seloger.com"]

    custom_settings = {
        # Respect : évite d’être trop agressif
        "USER_AGENT": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "DOWNLOAD_DELAY": 1.0,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 1.0,
        "AUTOTHROTTLE_MAX_DELAY": 10.0,
        "ROBOTSTXT_OBEY": True,
    }

    def __init__(self, search_url: str = None, max_links: int = 10, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not search_url:
            raise CloseSpider("Tu dois fournir -a search_url='<URL de recherche SeLoger>'")
        self.search_url = search_url
        self.max_links = int(max_links)
        self.collected = 0
        self.seen = set()
        self.current_page = 1

        # motif d'URL d’annonce SeLoger (achat/location)
        self.annonce_regex = re.compile(r"^https?://(?:www\.)?seloger\.com/annonces/(?:achat|location)/", re.I)

    def start_requests(self):
        first_url = set_or_add_page_param(self.search_url, self.current_page)
        yield scrapy.Request(first_url, callback=self.parse)

    def parse(self, response):
        # Récupère toutes les balises <a> et filtre sur le motif d’annonce
        hrefs = response.css("a::attr(href)").getall()
        for href in hrefs:
            if href.startswith("/"):
                href = response.urljoin(href)

            if self.annonce_regex.match(href):
                if href not in self.seen:
                    self.seen.add(href)
                    self.collected += 1
                    # On émet l’item (lien) – pas d’annonce en dur
                    yield {"url": href}

                    if self.collected >= self.max_links:
                        raise CloseSpider(f"Atteint {self.max_links} liens")

        # Si on n’a pas encore atteint le quota, on pagine
        if self.collected < self.max_links:
            self.current_page += 1
            next_url = set_or_add_page_param(self.search_url, self.current_page)
            yield scrapy.Request(next_url, callback=self.parse)
