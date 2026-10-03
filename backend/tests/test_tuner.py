"""Tuner + device-detection tests (torch-aware, skip when torch absent)."""
from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.inference.device import DeviceInfo, detect_device  # noqa: E402
from app.inference.tuner import PROFILES, TorchTuner  # noqa: E402

try:
    import torch  # noqa: F401
    TORCH = True
except Exception:
    TORCH = False


@dataclass
class _FakeDevice:
    label: str = "Test CPU"
    rocm_version: str = ""
    accelerator_available: bool = False


class TestProfiles(unittest.TestCase):
    def test_four_profiles_exist(self):
        self.assertEqual(
            set(PROFILES), {"throughput", "balanced", "quality", "low_vram"}
        )

    def test_profile_fields(self):
        for p in PROFILES.values():
            self.assertIn(p.matmul_precision, ("highest", "high", "medium"))
            self.assertIn(p.attention_backend, ("flash", "mem_efficient", "math"))
            self.assertGreaterEqual(p.batch_size, 1)

    def test_unknown_profile_raises(self):
        tuner = TorchTuner(_FakeDevice())
        with self.assertRaises(KeyError):
            tuner.set_profile("turbo")

    def test_set_profile_switches_active(self):
        tuner = TorchTuner(_FakeDevice())
        tuner.set_profile("quality")
        self.assertEqual(tuner.active_profile.key, "quality")
        self.assertTrue(tuner.available_profiles()[2]["active"])

    def test_invalid_startup_profile_falls_back_to_balanced(self):
        tuner = TorchTuner(_FakeDevice(), active_profile="nope")
        self.assertEqual(tuner.active_profile.key, "balanced")


@unittest.skipUnless(TORCH, "torch not installed")
class TestTorchIntegration(unittest.TestCase):
    def test_device_detection_reports_torch_version(self):
        device = detect_device()
        self.assertTrue(device.torch_version)
        if not device.accelerator_available:
            self.assertEqual(device.backend, "cpu")
            self.assertTrue(any("PyTorch" in n for n in device.notes))

    def test_startup_applies_profile_matmul_precision(self):
        tuner = TorchTuner(_FakeDevice(), active_profile="quality")
        self.assertEqual(torch.get_float32_matmul_precision(), "highest")

    def test_set_profile_reapplies_matmul_precision(self):
        tuner = TorchTuner(_FakeDevice(), active_profile="quality")
        tuner.set_profile("throughput")
        self.assertEqual(torch.get_float32_matmul_precision(), "high")
        tuner.set_profile("low_vram")
        self.assertEqual(torch.get_float32_matmul_precision(), "medium")
        # restore the engine default for other tests
        tuner.set_profile("balanced")

    def test_benchmark_runs_real_cpu_kernels(self):
        tuner = TorchTuner(_FakeDevice())
        result = tuner.benchmark(local_synth=lambda text: text.upper())
        self.assertEqual(result.mode, "cpu")
        self.assertIn("math", result.attention_ms)
        self.assertGreater(result.attention_ms["math"], 0)
        self.assertGreater(result.matmul_ms, 0)
        self.assertGreater(result.matmul_tflops, 0)
        self.assertEqual(result.matmul_label, "matmul 512×512")
        # calibration still runs alongside kernel benchmarks
        self.assertGreater(result.calibration_tokens_per_sec, 0)
        # flash may or may not expose a CPU kernel depending on torch version
        flash_ms = result.attention_ms.get("flash")
        self.assertTrue(flash_ms is None or flash_ms > 0)

    def test_sdpa_context_maps_flash_to_math_on_cpu(self):
        tuner = TorchTuner(_FakeDevice(), active_profile="balanced")  # flash profile
        with tuner.sdpa_kernel_ctx():
            q = torch.randn(1, 4, 64, 32)
            out = torch.nn.functional.scaled_dot_product_attention(q, q, q)
        self.assertEqual(out.shape, q.shape)

    def test_benchmark_dict_roundtrip(self):
        tuner = TorchTuner(_FakeDevice())
        tuner.benchmark(local_synth=lambda text: text)
        payload = tuner.last_benchmark.as_dict()
        self.assertIn(payload["mode"], ("cpu", "gpu", "cpu_calibration", "unavailable"))
        self.assertIn("matmul_label", payload)


if __name__ == "__main__":
    unittest.main()
