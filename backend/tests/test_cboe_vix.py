import asyncio

import httpx

from app.providers.cboe_vix import VIX_HISTORY_URL, CboeVixProvider
from app.services.cache_service import JsonFileCache

CSV = "DATE,OPEN,HIGH,LOW,CLOSE\n09/25/2026,15.10,15.90,14.80,15.20\n09/28/2026,15.30,16.40,15.00,16.05\n"


def test_vix_follows_cboe_redirect_and_reads_latest_close(tmp_path):
    moved_to = "https://cdn-api.cboe.com/moved/VIX_History.csv"
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if str(request.url) == VIX_HISTORY_URL:
            return httpx.Response(307, headers={"Location": moved_to})
        return httpx.Response(200, text=CSV)

    provider = CboeVixProvider(cache=JsonFileCache(tmp_path), max_retries=0, transport=httpx.MockTransport(handler))
    data = asyncio.run(provider.get_vix_data())

    assert seen == [VIX_HISTORY_URL, moved_to]
    assert data["value"] == 16.05
    assert data["as_of"].startswith("2026-09-28")
