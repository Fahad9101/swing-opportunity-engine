from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path

import httpx

from app.core.config import get_settings


COMPANYFACTS_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
SUBMISSIONS_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
STREAM_CHUNK_BYTES = 1024 * 1024


async def _download_archive(url: str, destination: Path) -> Path:
    """Download an SEC ZIP with a normal streamed GET.

    SEC edge nodes can reject HEAD requests from some hosted runners even when
    ordinary GET requests are permitted. The previous downloader depended on a
    successful HEAD followed by parallel range requests. This implementation
    avoids that transport assumption while preserving retries, atomic replace,
    ZIP integrity validation, and the same destination paths.
    """

    settings = get_settings()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    headers = {
        "User-Agent": settings.sec_user_agent,
        "Accept": "application/zip,application/octet-stream,*/*",
        "Accept-Encoding": "identity",
    }

    timeout = httpx.Timeout(connect=30.0, read=300.0, write=60.0, pool=60.0)
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                if temporary.exists():
                    temporary.unlink()
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with temporary.open("wb") as target:
                        async for chunk in response.aiter_bytes(STREAM_CHUNK_BYTES):
                            target.write(chunk)
                if not temporary.exists() or temporary.stat().st_size == 0:
                    raise ValueError("SEC archive download was empty")
                with zipfile.ZipFile(temporary) as archive:
                    corrupt = archive.testzip()
                    if corrupt:
                        raise ValueError(f"Corrupt SEC archive entry: {corrupt}")
                temporary.replace(destination)
                return destination
            except (httpx.HTTPError, OSError, ValueError, zipfile.BadZipFile) as exc:
                last_error = exc
                if temporary.exists():
                    temporary.unlink()
                if attempt == 3:
                    break
                await asyncio.sleep(1.0 * (2**attempt))

    assert last_error is not None
    raise last_error


async def download() -> Path:
    """Backward-compatible companyfacts downloader."""
    return await _download_archive(COMPANYFACTS_URL, get_settings().sec_companyfacts_zip_path)


async def download_submissions() -> Path:
    return await _download_archive(SUBMISSIONS_URL, get_settings().sec_submissions_zip_path)


async def download_all() -> tuple[Path, Path]:
    companyfacts = await download()
    submissions = await download_submissions()
    return companyfacts, submissions


def main() -> None:
    companyfacts, submissions = asyncio.run(download_all())
    print(f"companyfacts={companyfacts}")
    print(f"submissions={submissions}")


if __name__ == "__main__":
    main()
