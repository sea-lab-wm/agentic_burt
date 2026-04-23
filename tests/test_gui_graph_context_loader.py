import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gui_graph_context_management import loader


class ActiveBugIdDiscoveryTests(unittest.TestCase):
    def test_list_active_bug_ids_only_returns_loadable_runtime_contexts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            context_root = Path(tmp_dir)
            self._write_context(
                context_root / "bug10" / "context.json",
                {
                    "transitions": ["transition A"],
                    "application_name": "Test App",
                    "screen_names_and_descriptions": ["Screen A"],
                },
            )
            self._write_context(
                context_root / "bug2" / "context.json",
                {
                    "transitions": ["transition B"],
                    "application_name": "Test App",
                    "screen_names_and_descriptions": ["Screen B"],
                },
            )
            self._write_context(
                context_root / "bug11" / "context.json",
                {
                    "transitions": [],
                    "application_name": "Test App",
                    "screen_names_and_descriptions": [],
                },
            )
            self._write_context(
                context_root / "bug12" / "context.json",
                {
                    "transitions": ["transition C"],
                    "application_name": "",
                    "screen_names_and_descriptions": ["Screen C"],
                },
            )
            (context_root / "bug13").mkdir()
            (context_root / "bugoops").mkdir()
            (context_root / "bug14").mkdir()
            (context_root / "bug14" / "context.json").write_text("{not-json", encoding="utf-8")

            with patch.object(loader, "CONTEXT_ROOT", context_root):
                self.assertEqual(loader.list_active_bug_ids(), [2, 10])

    @staticmethod
    def _write_context(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
