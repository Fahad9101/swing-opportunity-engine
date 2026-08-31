from __future__ import annotations


class ProviderError(Exception):
    def __init__(self, provider: str, code: str, message: str, *, retryable: bool, ticker: str | None = None, endpoint: str | None = None, status_code: int | None = None):
        self.provider = provider
        self.code = code
        self.message = message
        self.retryable = retryable
        self.ticker = ticker
        self.endpoint = endpoint
        self.status_code = status_code
        super().__init__(message)

    def as_dict(self) -> dict:
        return {"provider": self.provider, "code": self.code, "message": self.message, "retryable": self.retryable, "ticker": self.ticker, "endpoint": self.endpoint, "status_code": self.status_code}

