import unittest
from unittest.mock import patch

from app.runtime import find_codex


class CodexLocationTests(unittest.TestCase):
    def test_new_mac_bundle_is_found_without_path(self):
        bundle = '/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'
        with patch('app.runtime.shutil.which', return_value=None), \
             patch('app.runtime.Path.is_file', lambda path: str(path) == bundle):
            self.assertEqual(find_codex(), bundle)

    def test_explicit_and_path_candidates_take_precedence(self):
        with patch('app.runtime.shutil.which', return_value='/local/codex'), \
             patch('app.runtime.Path.is_file', return_value=True):
            self.assertEqual(find_codex('/explicit/codex'), '/explicit/codex')
            self.assertEqual(find_codex(), '/local/codex')

    def test_missing_cli_returns_none(self):
        with patch('app.runtime.shutil.which', return_value=None), \
             patch('app.runtime.Path.is_file', return_value=False):
            self.assertIsNone(find_codex())
