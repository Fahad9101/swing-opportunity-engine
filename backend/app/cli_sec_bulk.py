from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path

import httpx

from app.core.config import get_settings


COMPANYFACTS_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
SUBMISSIONS_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
STREAM_CHUNK_BYTES = 1024 * 1024


def _valid_zip(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            return archive.testzip() is None
    except (OSError, zipfile.BadZipFile):
        return False


async def _download_archive(url: str, destination: Path) -> Path:
    """Download an SEC ZIP with validated-cache reuse and streamed GET.

    GitHub-hosted runners can intermittently receive SEC edge 403 responses even
    with a declared User-Agent. A previously validated nightly archive is safer
    than repeatedly hammering the SEC endpoint. The GitHub workflow therefore
    restores a dated Actions cache; this function reuses it only after ZIP
    integrity validation. If no valid cache is present, it performs a normal
    streamed GET with bounded exponential retries.
    """

    if _valid_zip(destination):
        return destination

    settings = get_settings()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    headers = {
        "User-Agent": settings.sec_user_agent,
        "Accept": "application/zip,application/octet-stream,*/*",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
    }

    timeout = httpx.Timeout(connect=30.0, read=300.0, write=60.0, pool=60.0)
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True, http2=False) as client:
        last_error: Exception | None = None
        for attempt in range(6):
            try:
                if temporary.exists():
                    temporary.unlink()
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with temporary.open("wb") as target:
                        async for chunk in response.aiter_bytes(STREAM_CHUNK_BYTES):
                            target.write(chunk)
                if not _valid_zip(temporary):
                    raise ValueError("SEC archive download failed ZIP integrity validation")
                temporary.replace(destination)
                return destination
            except (httpx.HTTPError, OSError, ValueError, zipfile.BadZipFile) as exc:
                last_error = exc
                if temporary.exists():
                    temporary.unlink()
                if attempt == 5:
                    break
                await asyncio.sleep(min(60.0, 2.0 * (2**attempt)))

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
