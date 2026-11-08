"""Shared HTTP client for all sources.

Policy:
* network errors, timeouts and retryable statuses (5xx, 429 by default) are
  retried with exponential backoff (2 s, 4 s, 8 s, 16 s by default);
* "business" statuses (200 and 404 by default) are returned to the caller,
  who stores them in bronze together with ``http_status``;
* anything else (e.g. 400, 403) raises ``UnexpectedStatusError`` at once,
  and a failure that persists after the last retry raises
  ``SourceUnavailableError`` - never a silent empty result.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from kyb.storage import atomic_open

log = logging.getLogger(__name__)

DEFAULT_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
DEFAULT_BUSINESS_STATUSES = frozenset({200, 404})
NETWORK_ERRORS = (
    requests.ConnectionError,
    requests.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


class HttpError(Exception):
    """Base class for HTTP problems that must be visible to the operator."""


class SourceUnavailableError(HttpError):
    """Network failure or retryable status that persisted after all retries."""


class UnexpectedStatusError(HttpError):
    """Non-retryable status that is not an accepted business result."""

    def __init__(self, url: str, status: int, body: str) -> None:
        super().__init__(f"HTTP {status} for {url}: {body[:300]}")
        self.url = url
        self.status = status
        self.body = body


class IncompleteDownloadError(HttpError):
    """Fewer bytes were received than the server announced."""


class InvalidPayloadError(HttpError):
    """The status looks fine but the body is not what the API returns.

    Seen live: the VAT White List answers HTTP 200 with an HTML bot-protection
    page (Imperva Incapsula) when it blocks a client. Such a body must not be
    treated - or cached - as a valid answer.
    """


@dataclass(frozen=True)
class HttpResult:
    url: str
    status: int
    text: str
    content_type: str
    attempts: int
    elapsed_s: float


def parse_json_payload(text: str, required_keys: Collection[str] = ()) -> Any:
    """Parse an API body; raise InvalidPayloadError unless it is JSON with the keys."""
    try:
        data = json.loads(text)
    except ValueError:
        hint = " (looks like an HTML/WAF page)" if text.lstrip().lower().startswith("<") else ""
        raise InvalidPayloadError(f"expected JSON{hint}: {text[:200]!r}") from None
    missing = [k for k in required_keys if not (isinstance(data, dict) and k in data)]
    if missing:
        raise InvalidPayloadError(f"JSON body misses expected key(s) {missing}: {text[:200]!r}")
    return data


def ensure_json(result: HttpResult, required_keys: Collection[str] = ()) -> Any:
    """Validate an HttpResult body (see parse_json_payload), naming the URL on failure."""
    try:
        return parse_json_payload(result.text, required_keys)
    except InvalidPayloadError as exc:
        raise InvalidPayloadError(f"HTTP {result.status} for {result.url}: {exc}") from None


@dataclass(frozen=True)
class StreamResult:
    url: str
    status: int
    value: Any  # whatever the sink returned (e.g. the written path or row counts)
    size_bytes: int
    sha256: str
    sha1: str
    content_type: str
    attempts: int


class ChecksumMismatchError(IncompleteDownloadError):
    """The received bytes do not match the checksum published by the source."""


class _VerifyingChunks:
    """Yields body chunks while hashing them; checks length and SHA-1 at the end.

    The check fires *inside* the iteration, i.e. while the sink is still
    consuming, so a sink that writes through ``atomic_open`` discards a
    truncated or corrupted file instead of committing it.
    """

    def __init__(self, chunks: Iterable[bytes], url: str, expected_size: int | None, expected_sha1: str | None):
        self._chunks = chunks
        self.url = url
        self.expected_size = expected_size
        self.expected_sha1 = expected_sha1
        self.size = 0
        self.sha256 = hashlib.sha256()
        self.sha1 = hashlib.sha1()  # noqa: S324 - integrity check against the published SHA-1
        self.finished = False
        self._gen = self._run()

    def __iter__(self) -> Iterator[bytes]:
        return self._gen

    def _run(self) -> Iterator[bytes]:
        for chunk in self._chunks:
            if chunk:
                self.size += len(chunk)
                self.sha256.update(chunk)
                self.sha1.update(chunk)
                yield chunk
        if self.expected_size is not None and self.size != self.expected_size:
            raise IncompleteDownloadError(f"{self.url}: got {self.size} of {self.expected_size} bytes")
        if self.expected_sha1 and self.sha1.hexdigest() != self.expected_sha1:
            raise ChecksumMismatchError(
                f"{self.url}: SHA-1 {self.sha1.hexdigest()} differs from published {self.expected_sha1}"
            )
        self.finished = True


def _decode(response: requests.Response) -> str:
    # requests falls back to ISO-8859-1 for text/* without charset; JSON is UTF-8 by spec
    encoding = response.encoding
    content_type = response.headers.get("Content-Type", "")
    if encoding is None or ("json" in content_type and "charset" not in content_type.lower()):
        encoding = "utf-8"
    return response.content.decode(encoding, errors="replace")


class HttpClient:
    def __init__(
        self,
        *,
        timeout: float = 30.0,
        max_retries: int = 4,
        backoff_base: float = 2.0,
        max_backoff: float = 60.0,
        user_agent: str = "kyb-screening/0.1",
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.max_backoff = max_backoff
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.session.headers["Accept"] = "application/json, text/csv;q=0.9, */*;q=0.5"
        self.sleep = sleep

    @classmethod
    def from_settings(cls, http_settings: Mapping[str, Any], **overrides: Any) -> HttpClient:
        params: dict[str, Any] = {
            "timeout": http_settings.get("timeout_seconds", 30),
            "max_retries": http_settings.get("max_retries", 4),
            "backoff_base": http_settings.get("backoff_base_seconds", 2),
            "user_agent": http_settings.get("user_agent", "kyb-screening/0.1"),
        }
        params.update(overrides)
        return cls(**params)

    # ------------------------------------------------------------------ helpers
    def _delay(self, attempt: int, retry_after: str | None) -> float:
        delay = self.backoff_base * (2 ** (attempt - 1))
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass  # HTTP-date form of Retry-After: keep the exponential delay
        return min(delay, self.max_backoff)

    def _wait_or_raise(
        self, url: str, attempt: int, max_retries: int, reason: str, retry_after: str | None = None
    ) -> None:
        if attempt > max_retries:
            raise SourceUnavailableError(f"GET {url} failed after {attempt} attempt(s): {reason}")
        delay = self._delay(attempt, retry_after)
        log.warning("GET %s: %s - retry %d/%d in %.0f s", url, reason, attempt, max_retries, delay)
        self.sleep(delay)

    # --------------------------------------------------------------------- API
    def get(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        *,
        business_statuses: Collection[int] = DEFAULT_BUSINESS_STATUSES,
        retry_statuses: Collection[int] = DEFAULT_RETRY_STATUSES,
        max_retries: int | None = None,
        before_attempt: Callable[[], None] | None = None,
    ) -> HttpResult:
        """GET with retries. ``before_attempt`` runs before every request that
        is actually sent (used e.g. to count requests against a daily quota)."""
        retries = self.max_retries if max_retries is None else max_retries
        attempt = 0
        while True:
            attempt += 1
            if before_attempt is not None:
                before_attempt()
            started = time.monotonic()
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except NETWORK_ERRORS as exc:
                self._wait_or_raise(url, attempt, retries, f"network error: {exc}")
                continue
            status = response.status_code
            if status in business_statuses:
                elapsed = time.monotonic() - started
                log.info("GET %s -> %d (%d B, %.2f s)", response.url, status, len(response.content), elapsed)
                return HttpResult(
                    url=response.url,
                    status=status,
                    text=_decode(response),
                    content_type=response.headers.get("Content-Type", ""),
                    attempts=attempt,
                    elapsed_s=round(elapsed, 3),
                )
            if status in retry_statuses:
                self._wait_or_raise(
                    response.url, attempt, retries, f"HTTP {status}", response.headers.get("Retry-After")
                )
                continue
            raise UnexpectedStatusError(response.url, status, _decode(response))

    def stream(
        self,
        url: str,
        sink: Callable[[Iterable[bytes]], Any],
        *,
        expected_sha1: str | None = None,
        retry_statuses: Collection[int] = DEFAULT_RETRY_STATUSES,
        chunk_size: int = 1 << 20,
    ) -> StreamResult:
        """GET a large body and pass its chunks to ``sink`` without buffering it.

        Transfer errors, truncation and checksum mismatches restart the whole
        transfer (the sink is called again), so sinks must write atomically.
        """
        attempt = 0
        while True:
            attempt += 1
            try:
                with self.session.get(url, stream=True, timeout=self.timeout) as response:
                    status = response.status_code
                    if status in retry_statuses:
                        self._wait_or_raise(
                            response.url, attempt, self.max_retries, f"HTTP {status}",
                            response.headers.get("Retry-After"),
                        )
                        continue
                    if status != 200:
                        raise UnexpectedStatusError(response.url, status, _decode(response))
                    length = response.headers.get("Content-Length")
                    # with Content-Encoding the announced length is the compressed size
                    expected_size = int(length) if length and not response.headers.get("Content-Encoding") else None
                    chunks = _VerifyingChunks(
                        response.iter_content(chunk_size=chunk_size), response.url, expected_size, expected_sha1
                    )
                    value = sink(chunks)
                    if not chunks.finished:
                        raise RuntimeError(f"sink for {url} did not consume the whole body")
                    log.info("STREAM %s -> %d (%d B)", response.url, status, chunks.size)
                    return StreamResult(
                        url=response.url,
                        status=status,
                        value=value,
                        size_bytes=chunks.size,
                        sha256=chunks.sha256.hexdigest(),
                        sha1=chunks.sha1.hexdigest(),
                        content_type=response.headers.get("Content-Type", ""),
                        attempts=attempt,
                    )
            except (*NETWORK_ERRORS, IncompleteDownloadError) as exc:
                self._wait_or_raise(url, attempt, self.max_retries, f"transfer error: {exc}")

    def download(self, url: str, dest: Path, **kwargs: Any) -> StreamResult:
        """Stream a (large) file to ``dest`` atomically; ``value`` is the path."""

        def write(chunks: Iterable[bytes]) -> Path:
            with atomic_open(dest, "wb") as fh:
                for chunk in chunks:
                    fh.write(chunk)
            return dest

        return self.stream(url, write, **kwargs)
