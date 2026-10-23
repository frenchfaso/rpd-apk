"""Bounded retries for upstream GETs; callers still authenticate every response."""
import errno
import http.client
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime

ATTEMPTS = 5
TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504}
TRANSIENT_ERRNO = {errno.ECONNABORTED, errno.ECONNREFUSED, errno.ECONNRESET,
                   errno.EHOSTUNREACH, errno.ENETUNREACH, errno.ETIMEDOUT}


def fetch(url):
    for attempt in range(ATTEMPTS):
        delay = 5 * 2**attempt
        try:
            with urllib.request.urlopen(url, timeout=90) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            error.close()
            if error.code not in TRANSIENT_HTTP:
                raise
            retry_after = (error.headers or {}).get('Retry-After')
            if retry_after:
                try:
                    seconds = int(retry_after)
                except ValueError:
                    try:
                        seconds = parsedate_to_datetime(retry_after).timestamp() - time.time()
                    except (ValueError, TypeError, OverflowError):
                        seconds = 0
                delay = max(delay, seconds)
            # Do not retry earlier than requested, or stall CI indefinitely.
            if delay > 120 or attempt == ATTEMPTS - 1:
                raise
        except urllib.error.URLError as error:
            reason = error.reason
            if (isinstance(reason, ssl.SSLError) or
                    not (isinstance(reason, TimeoutError) or
                         isinstance(reason, OSError) and reason.errno in TRANSIENT_ERRNO or
                         isinstance(reason, socket.gaierror) and reason.errno == socket.EAI_AGAIN) or
                    attempt == ATTEMPTS - 1):
                raise
        except (TimeoutError, ConnectionError, http.client.IncompleteRead):
            if attempt == ATTEMPTS - 1:
                raise
        print(f'Download interrupted; retry {attempt + 1}/{ATTEMPTS - 1} '
              f'in {delay:g}s: {url}', file=sys.stderr)
        time.sleep(delay)
