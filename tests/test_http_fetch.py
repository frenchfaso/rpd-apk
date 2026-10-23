import errno
from email.message import Message
import http.client
import importlib.util
import io
from pathlib import Path
import socket
import ssl
import sys
import unittest
from unittest import mock
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import http_fetch


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.open = mock.patch.object(http_fetch.urllib.request, 'urlopen').start()
        self.sleep = mock.patch.object(http_fetch.time, 'sleep').start()
        self.addCleanup(mock.patch.stopall)
        self.open.return_value = io.BytesIO(b'complete')
        self.url = 'https://example.test/source'

    def http_error(self, code, retry_after=None):
        headers = Message()
        if retry_after is not None:
            headers['Retry-After'] = retry_after
        return urllib.error.HTTPError(self.url, code, 'test', headers, io.BytesIO())

    def test_success_needs_one_request(self):
        self.assertEqual(http_fetch.fetch(self.url), b'complete')
        self.open.assert_called_once_with(self.url, timeout=90)
        self.sleep.assert_not_called()

    def test_rate_limit_waits_then_retries(self):
        error = self.http_error(429, '30')
        self.open.side_effect = [error, io.BytesIO(b'complete')]
        self.assertEqual(http_fetch.fetch(self.url), b'complete')
        self.sleep.assert_called_once_with(30)
        self.assertTrue(error.closed)

    def test_http_date_retry_after(self):
        self.open.side_effect = [self.http_error(503, 'Thu, 01 Jan 1970 00:01:00 GMT'),
                                 io.BytesIO(b'complete')]
        with mock.patch.object(http_fetch.time, 'time', return_value=10):
            self.assertEqual(http_fetch.fetch(self.url), b'complete')
        self.sleep.assert_called_once_with(50)

    def test_unreachable_network_retries(self):
        self.open.side_effect = [urllib.error.URLError(OSError(errno.ENETUNREACH, 'network')),
                                 io.BytesIO(b'complete')]
        self.assertEqual(http_fetch.fetch(self.url), b'complete')
        self.sleep.assert_called_once_with(5)

    def test_temporary_dns_error_retries(self):
        self.open.side_effect = [urllib.error.URLError(socket.gaierror(socket.EAI_AGAIN, 'DNS')),
                                 io.BytesIO(b'complete')]
        self.assertEqual(http_fetch.fetch(self.url), b'complete')
        self.sleep.assert_called_once_with(5)

    def test_truncated_body_is_discarded(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.side_effect = http.client.IncompleteRead(b'partial')
        self.open.side_effect = [response, io.BytesIO(b'complete')]
        self.assertEqual(http_fetch.fetch(self.url), b'complete')
        response.__exit__.assert_called_once()
        self.sleep.assert_called_once_with(5)

    def test_retry_budget_is_finite(self):
        error = self.http_error(503)
        self.open.side_effect = error
        with self.assertRaises(urllib.error.HTTPError) as raised:
            http_fetch.fetch(self.url)
        self.assertIs(raised.exception, error)
        self.assertEqual(self.open.call_count, 5)
        self.assertEqual(self.sleep.call_args_list,
                         [mock.call(5), mock.call(10), mock.call(20), mock.call(40)])

    def test_permanent_errors_are_not_retried(self):
        for error in (self.http_error(401), self.http_error(404),
                      urllib.error.URLError(ssl.SSLCertVerificationError('untrusted')),
                      ValueError('validation failed')):
            with self.subTest(error=error):
                self.open.reset_mock()
                self.open.side_effect = error
                with self.assertRaises(type(error)):
                    http_fetch.fetch(self.url)
                self.open.assert_called_once()
                self.sleep.assert_not_called()

    def test_long_rate_limit_fails_without_early_retry(self):
        self.open.side_effect = self.http_error(429, '600')
        with self.assertRaises(urllib.error.HTTPError):
            http_fetch.fetch(self.url)
        self.open.assert_called_once()
        self.sleep.assert_not_called()

    def test_archive_url_policy_is_checked_before_download(self):
        spec = importlib.util.spec_from_file_location('upstream', ROOT/'scripts/update-upstream.py')
        update = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(update)
        with self.assertRaisesRegex(ValueError, 'Unapproved upstream URL'):
            update.fetch('https://example.test/unsigned')
        self.open.assert_not_called()
