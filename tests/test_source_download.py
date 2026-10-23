import http.server
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('curl'), 'curl is required')
class SourceDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        shutil.copyfile(ROOT/'scripts/source-download.curlrc',
                        self.directory/'.curlrc')
        self.requests = 0
        self.statuses = []
        test = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                test.requests += 1
                status = test.statuses.pop(0) if test.statuses else 200
                self.send_response(status)
                self.send_header('Content-Length', '7')
                if status == 429:
                    self.send_header('Retry-After', '1')
                self.end_headers()
                self.wfile.write(b'archive')

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever,
                                  kwargs={'poll_interval': 0.05}, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)

    def download(self, *options):
        # Match abuild-fetch's curl invocation, including its output file.
        url = 'http://127.0.0.1:' + str(self.server.server_port) + '/source'
        return subprocess.run(
            ['curl', '-L', '-f', '-o', str(self.directory/'source'),
             '--silent', '--show-error', '--noproxy', '*', *options, url],
            env={**os.environ, 'CURL_HOME': str(self.directory)},
            capture_output=True, text=True, timeout=15)

    def test_rate_limit_is_retried_using_default_config(self):
        self.statuses = [429, 200]
        result = self.download()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.requests, 2)
        self.assertEqual((self.directory/'source').read_bytes(), b'archive')

    def test_missing_source_is_not_retried(self):
        self.statuses = [404, 200]
        result = self.download()
        self.assertEqual(result.returncode, 22, result.stderr)
        self.assertEqual(self.requests, 1)

    def test_rate_limit_retries_are_bounded(self):
        self.statuses = [429] * 6
        result = self.download('--retry-delay', '1')
        self.assertEqual(result.returncode, 22, result.stderr)
        self.assertEqual(self.requests, 5)
