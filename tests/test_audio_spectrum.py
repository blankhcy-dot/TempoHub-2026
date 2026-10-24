"""Numerical regression checks; no Qt runtime or audio device is needed."""

import ast
import math
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np


def load_update():
    path = Path(__file__).resolve().parents[1] / "src/app/utils/tempo_scene_engine.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    scene_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SceneEngine")
    update = next(node for node in scene_class.body if isinstance(node, ast.FunctionDef) and node.name == "_update_audio_spectrum")
    namespace = {"math": math, "AUDIO_BARS": 32, "_clamp": lambda value, low, high: max(low, min(high, value))}
    exec(compile(ast.Module(body=[update], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["_update_audio_spectrum"]


def reference(data, samplerate):
    mono = np.asarray(data, dtype=np.float32)
    if mono.ndim > 1:
        mono = mono.mean(axis=1)
    block = mono[-1024:] if mono.size >= 1024 else np.resize(mono, 1024)
    spectrum = np.abs(np.fft.rfft(block * np.hanning(block.size)))
    frequencies = np.fft.rfftfreq(block.size, 1.0 / samplerate)
    edges = np.geomspace(35.0, min(18000.0, samplerate / 2), 33)
    levels = []
    for band in range(32):
        selected = spectrum[(frequencies >= edges[band]) & (frequencies < edges[band + 1])]
        power = float(selected.mean()) if selected.size else 0.0
        levels.append(max(0.0, min(1.0, (20 * math.log10(power + 1e-8) + 62) / 50)))
    return levels


class AudioTests(unittest.TestCase):
    def test_cached_fft_matches_reference_across_signals_and_sample_rates(self):
        update = load_update()
        state = SimpleNamespace(_fft_plan=None, _lock=threading.RLock())
        random = np.random.default_rng(42)
        for samplerate in (48000, 44100, 32000):
            tone = 0.02 * np.sin(2 * np.pi * 1000 * np.arange(1024) / samplerate)
            for data in (np.zeros(1024), tone, np.column_stack((tone, tone * 0.5)), random.normal(0, 0.01, 4096), tone[:128]):
                update(state, data, samplerate, np)
                np.testing.assert_allclose(state._audio_levels, reference(data, samplerate), atol=1e-12)
                self.assertEqual(len(state._audio_wave), 128)
                self.assertTrue(math.isfinite(state._audio_rms_db))
                self.assertTrue(math.isfinite(state._audio_peak_db))
            plan = state._fft_plan
            update(state, tone, samplerate, np)
            self.assertIs(state._fft_plan, plan)


if __name__ == "__main__":
    unittest.main(verbosity=2)
