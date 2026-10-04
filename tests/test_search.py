import httpx

from crypto_terminal.history import Product, fetch_products, search_products


def product(pid, name=""):
    base, quote = pid.split("-")
    return Product(pid, base, quote, name)


PRODUCTS = [product(p, "Solana") for p in ("SOL-ETH", "SOL-BTC", "SOL-GBP", "SOL-EUR", "SOL-USDT", "SOL-USD")] + [
    product("SOLV-USD", "Solv Protocol"), product("BTC-USD", "Bitcoin"), product("BTC-USDC", "Bitcoin"),
    product("ESOL-USD", "Ethena Solana"),
]


def ids(products):
    return [p.id for p in products]


def test_search_ranks_exact_then_quote_currency():
    expected = ["SOL-USD", "SOL-USDT", "SOL-EUR", "SOL-GBP", "SOL-BTC", "SOL-ETH", "SOLV-USD"]
    assert ids(search_products(PRODUCTS, "sol")) == expected
    assert ids(search_products(PRODUCTS, "SOLANA")) == expected[:-1]  # exact name; "Solv" doesn't start with it
    assert ids(search_products(PRODUCTS, "bitcoin")) == ["BTC-USD", "BTC-USDC"]


def test_search_no_matches():
    assert search_products(PRODUCTS, "zzzz") == []


async def test_fetch_products_filters_and_names():
    products = [
        {"id": "SOL-USD", "status": "online", "trading_disabled": False},
        {"id": "SOL-EUR", "status": "delisted", "trading_disabled": True},
        {"id": "OLD-USD", "status": "online", "trading_disabled": True},
        {"id": "bad id", "status": "online", "trading_disabled": False},
        {"id": 7, "status": "online", "trading_disabled": False},
        "garbage",
        {"id": "XYZ-USD", "status": "online", "trading_disabled": False},
    ]
    currencies = [{"id": "SOL", "name": "Solana"}, {"id": "XYZ", "name": None}, "garbage"]

    def handler(request):
        return httpx.Response(200, json=products if request.url.path == "/products" else currencies)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await fetch_products(client) == [Product("SOL-USD", "SOL", "USD", "Solana"),
                                                Product("XYZ-USD", "XYZ", "USD", "")]


async def test_fetch_products_without_currencies():
    def handler(request):
        if request.url.path == "/currencies":
            return httpx.Response(500)
        return httpx.Response(200, json=[{"id": "SOL-USD", "status": "online", "trading_disabled": False}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await fetch_products(client) == [Product("SOL-USD", "SOL", "USD", "")]
