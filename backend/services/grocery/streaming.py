"""En mottagare för produkter som inte sparar dem längre än den måste.

VARFÖR DEN FINNS. Axfood-providern har streamat sedan den skrevs: varje
avdelning lämnas vidare till `on_products` direkt och glöms. City Gross och
Primat gjorde tvärtom - de byggde hela katalogen som en lista i minnet och
lämnade över den på slutet. City Gross är ~8 700 `RawProduct`, Primat en hel
Maxi-katalog med både prisrader och detaljsvar. Samtidigt kör processen
Chromium på en 512 MB-instans.

En OOM under bootstrap är dessutom värre än ett vanligt haveri: databasen
förblir tom, nästa boot ser en tom databas och startar samma bootstrap igen.
En hammarloop som varken lämnar data eller stannar av sig själv.

KONTRAKTET. `add()` tar emot en normaliserad produkt. Finns en `on_products`
lämnas produkterna vidare i batchar och släpps; finns ingen sparas de och
`drain()` ger tillbaka hela listan. Samma providerkod kan alltså både
strömma (importern) och returnera allt (ett direktanrop, ett test) utan att
någon av vägarna är en särskild kodgren nere i insamlingen.

Batchen är inte en optimering utan en gräns: den säger hur många produkter
som får finnas i minnet samtidigt. Importerns `save_batch` stagear varje
batch i SQLite och släpper den, så minnet blir O(batch) i stället för
O(katalog).
"""

import logging

logger = logging.getLogger("matjakt.grocery.streaming")

# 200 produkter är en kompromiss mellan två kostnader: varje flush är en
# transaktion i staging-tabellen (billig, men inte gratis) och varje ohanterad
# produkt är minne. En RawProduct med namn, kategori och bild-URL ligger kring
# 1 kB, så taket kostar ~200 kB - mot ~9 MB för en hel City Gross-katalog.
DEFAULT_BATCH_SIZE = 200


class ProductSink:
    """Tar emot produkter under en insamling och gör sig av med dem."""

    def __init__(self, on_products=None, batch_size: int = DEFAULT_BATCH_SIZE):
        self._on_products = on_products
        self._batch_size = max(1, int(batch_size))
        self._buffer: list = []
        self.count = 0
        self.batches = 0
        # Största antal produkter som någonsin legat i bufferten samtidigt.
        # Finns för testerna: "materialiserar inte hela katalogen" är ett
        # påstående som ska gå att mäta, inte en avsikt i en kommentar.
        self.peak_buffered = 0

    @property
    def streaming(self) -> bool:
        return self._on_products is not None

    def add(self, product) -> None:
        if product is None:
            return
        self._buffer.append(product)
        self.count += 1
        if len(self._buffer) > self.peak_buffered:
            self.peak_buffered = len(self._buffer)
        if self._on_products is not None and len(self._buffer) >= self._batch_size:
            self.flush()

    def flush(self) -> None:
        """Lämnar det som ligger i bufferten vidare och släpper det.

        Utan `on_products` är det här en no-op med flit: då ÄR bufferten
        resultatet, och att tömma den hade tappat katalogen."""
        if self._on_products is None or not self._buffer:
            return
        batch = self._buffer
        # Ny lista, inte .clear(): mottagaren äger batchen efter det här och
        # får inte se den tömmas under fötterna.
        self._buffer = []
        self.batches += 1
        self._on_products(batch)

    def drain(self) -> list:
        """Allt som ÄNNU INTE lämnats vidare, och som anroparen därför själv
        måste ta hand om. Tom lista när vi streamar."""
        self.flush()
        rest = self._buffer
        self._buffer = []
        return rest
