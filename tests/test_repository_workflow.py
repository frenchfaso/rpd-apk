"""Static publication boundaries for branch workflow_dispatch validation."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RepositoryWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT/'.github/workflows/repository.yml').read_text()
        self.jobs = dict(re.findall(r'^  ([a-z0-9]+):\n(.*?)(?=^  [a-z0-9]+:|\Z)',
                                    self.text.split('jobs:\n', 1)[1], re.M | re.S))

    def test_manual_branch_uses_its_exact_revision_without_persisted_credentials(self):
        prepare = self.jobs['prepare']
        self.assertIn("ref: ${{ github.event_name == 'schedule' && 'main' || github.sha }}", prepare)
        self.assertIn("persist-credentials: ${{ github.ref == 'refs/heads/main' }}", prepare)
        self.assertIn('echo "sha=$(git rev-parse HEAD)"', prepare)

    def test_only_main_can_mutate_or_follow_upstream_sources(self):
        prepare = self.jobs['prepare']
        for step in re.split(r'(?=^      - )', prepare, flags=re.M):
            if 'git push ' in step or 'git commit ' in step:
                self.assertIn("        if: github.ref == 'refs/heads/main'\n", step)
            if 'scripts/update-m10-kernel.py' in step:
                self.assertIn("if: github.ref == 'refs/heads/main' && github.event_name != 'push'", step)
        self.assertIn('git add upstream.lock.json m10-kernel.lock.json ports/', prepare)

    def test_branch_validation_cannot_sign_or_deploy(self):
        for name in ['sign', 'deploy']:
            self.assertIn("    if: github.ref == 'refs/heads/main'\n", self.jobs[name])
        for name, body in self.jobs.items():
            if '${{ secrets.' in body:
                self.assertEqual(name, 'sign')
        self.assertIn('needs: [prepare, qt6, runtime, kernel, webkit]', self.jobs['build'])
        self.assertIn('name: verified-test-build', self.jobs['build'])
