from __future__ import annotations

import asyncio
import shutil
import zipfile
from pathlib import Path

import httpx

from app.core.config import get_settings


URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
CHUNK_BYTES = 16 * 1024 * 1024


async def download() -> Path:
    settings = get_settings()
    destination = settings.sec_companyfacts_zip_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    part_dir = destination.with_suffix(".parts")
    part_dir.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": settings.sec_user_agent, "Accept-Encoding": "identity"}
    async with httpx.AsyncClient(timeout=120, headers=headers, follow_redirects=True) as client:
        head = await client.head(URL)
        head.raise_for_status()
        total = int(head.headers["Content-Length"])
        semaphore = asyncio.Semaphore(8)

        async def fetch(index: int, start: int, end: int) -> Path:
            output = part_dir / f"{index:05d}.part"
            expected = end - start + 1
            if output.exists() and output.stat().st_size == expected:
                return output
            async with semaphore:
                for attempt in range(4):
                    try:
                        response = await client.get(URL, headers={**headers, "Range": f"bytes={start}-{end}"})
                        response.raise_for_status()
                        if len(response.content) != expected:
                            raise ValueError("SEC range response length mismatch")
                        output.write_bytes(response.content)
                        return output
                    except (httpx.HTTPError, ValueError):
                        if attempt == 3:
                            raise
                        await asyncio.sleep(0.5 * (2**attempt))
            raise AssertionError("unreachable")

        ranges = [(index, start, min(start + CHUNK_BYTES - 1, total - 1)) for index, start in enumerate(range(0, total, CHUNK_BYTES))]
        parts = await asyncio.gather(*(fetch(*item) for item in ranges))
    temporary = destination.with_suffix(".zip.tmp")
    with temporary.open("wb") as target:
        for part in sorted(parts):
            with part.open("rb") as source:
                shutil.copyfileobj(source, target)
    if temporary.stat().st_size != total:
        raise ValueError("Combined SEC archive length mismatch")
    with zipfile.ZipFile(temporary) as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise ValueError(f"Corrupt SEC archive entry: {corrupt}")
    temporary.replace(destination)
    return destination


def main() -> None:
    print(asyncio.run(download()))


if __name__ == "__main__":
    main()
