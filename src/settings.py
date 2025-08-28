# Une liste de User-Agents populaires pour se faire passer pour un navigateur
USER_AGENT_LIST = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15',
]
# Activez le middleware rotatif et désactivez celui de Scrapy par défaut
DOWNLOADER_MIDDLEWARES = {
    'src.middlewares.RandomUserAgentMiddleware': 400,
    'scrapy.downloadermiddlewares.useragent.UserAgentMiddleware': None,
}

# Un délai de 250ms à 1.5s entre les requêtes
DOWNLOAD_DELAY = 1  
RANDOMIZE_DOWNLOAD_DELAY = True

# Active le middleware de délai automatique (utile si le site utilise un "gentil" anti-bot)
AUTOTHROTTLE_ENABLED = True