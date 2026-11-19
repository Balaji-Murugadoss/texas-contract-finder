"""One place for HTTP calls: timeouts, retries with backoff, and no API keys in logs."""
import logging
import random
import time

import httpx

import config

log = logging.getLogger(__name__)
RETRY_STATUS = {429, 500, 502, 503, 504}   # worth retrying; 400/401/403/404 are not


def request_with_retry(method: str, url: str, *, max_attempts: int = 4, timeout: float = 30, **kwargs):
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", config.USER_AGENT)
    reason = ""
    for attempt in range(1, max_attempts + 1):
        try:
            resp = httpx.request(method, url, headers=headers, timeout=timeout,
                                 follow_redirects=True, **kwargs)
            if resp.status_code not in RETRY_STATUS:
                resp.raise_for_status()   # 4xx errors stop here: retrying won't fix a bad key
                return resp
            reason = f"HTTP {resp.status_code}"
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            reason = type(exc).__name__
        if attempt == max_attempts:
            raise RuntimeError(f"{method} {url} failed after {max_attempts} attempts ({reason})")
        wait = 2 ** (attempt - 1) + random.random()      # 1s, 2s, 4s ... plus jitter
        log.warning("%s %s -> %s; retry %d in %.1fs", method, url, reason, attempt, wait)
        time.sleep(wait)
