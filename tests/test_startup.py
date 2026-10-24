"""Test the launcher without loading Qt or touching running desktop apps."""

import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app_dir = Path(self.directory.name)
        self.executable = self.app_dir / "EDIFIER TempoHub.exe"
        self.executable.touch()
        self.launch = Mock()
        self.api_get = Mock(return_value={"running": False})
        self.clock = SimpleNamespace(monotonic=Mock(return_value=0.0), sleep=Mock())
        tree = ast.parse((ROOT / "ui/lyrics_settings.py").read_text(encoding="utf-8"))
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef)
                        and node.name == "ensure_tempo_hub_running")
        namespace = {"APP_DIR": self.app_dir, "api_get": self.api_get,
                     "subprocess": SimpleNamespace(Popen=self.launch), "time": self.clock}
        exec(compile(ast.Module(body=[function], type_ignores=[]),
                     "lyrics_settings.py", "exec"), namespace)
        self.start = namespace[function.name]

    def test_background_api_does_not_skip_normal_hub_launch(self):
        # Reproduce a --startup instance whose API is already reachable.
        self.api_get.side_effect = lambda *a, **kw: (
            self.assertTrue(self.launch.called) or {"running": False})
        self.assertTrue(self.start())
        self.launch.assert_called_once_with(
            [str(self.executable)], cwd=str(self.app_dir), close_fds=True)

    def test_cold_start_waits_for_api(self):
        self.api_get.side_effect = [OSError("not listening"), {"running": True}]
        self.assertTrue(self.start())
        self.assertEqual(self.launch.call_count, 1)
        self.assertEqual(self.api_get.call_count, 2)
        self.clock.sleep.assert_called_once()

    def test_missing_executable_is_a_failure_even_if_api_responds(self):
        self.executable.unlink()
        self.assertFalse(self.start())
        self.launch.assert_not_called()
        self.api_get.assert_not_called()

    def test_launch_failure_is_reported(self):
        self.launch.side_effect = OSError("access denied")
        self.assertFalse(self.start())
        self.api_get.assert_not_called()

    def test_api_timeout_does_not_launch_multiple_hubs(self):
        self.api_get.side_effect = OSError("not listening")
        self.clock.monotonic.side_effect = [0.0, 0.0, 11.0]
        self.assertFalse(self.start())
        self.assertEqual(self.launch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
