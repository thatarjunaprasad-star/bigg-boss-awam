"""PyTorch tuning layer for the Awam inference engine.

Four inference profiles (throughput / balanced / quality / low_vram) map to
concrete torch switches: matmul precision, scaled-dot-product-attention
backend selection, optional torch.compile mode, and generation batch size.
On an AMD GPU this is a ROCm/HIP build of PyTorch, where SDPA dispatches to
the ROCm FlashAttention kernels. With a CPU-only torch install the same
profiles still drive `set_float32_matmul_precision`, and benchmarks run real
SDPA/matmul kernels on CPU.

`benchmark()` runs attention + matmul micro-kernels whenever torch with an
accelerator is present, real CPU kernels when torch is installed without an
accelerator, and otherwise calibrates the local engine's synthesis path —
so the dashboard always shows honest, measured numbers.
"""
from __future__ import annotations

import contextlib
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .device import DeviceInfo


@dataclass(frozen=True)
class TuningProfile:
    key: str
    label: str
    description: str
    matmul_precision: str        # torch.set_float32_matmul_precision
    attention_backend: str       # flash | mem_efficient | math
    compile_mode: str            # "" (off) | "default" | "max-autotune"
    batch_size: int
    dtype: str                   # "float16" | "bfloat16" | "float32"


PROFILES: dict[str, TuningProfile] = {
    p.key: p
    for p in [
        TuningProfile(
            key="throughput", label="Throughput",
            description="Max tokens/sec — flash attention, bf16, autotuned kernels.",
            matmul_precision="high", attention_backend="flash",
            compile_mode="max-autotune", batch_size=8, dtype="bfloat16",
        ),
        TuningProfile(
            key="balanced", label="Balanced",
            description="The house default — flash attention with bf16 compute.",
            matmul_precision="high", attention_backend="flash",
            compile_mode="default", batch_size=4, dtype="bfloat16",
        ),
        TuningProfile(
            key="quality", label="Quality",
            description="Full fp32 math attention — slow, unreasonably precise.",
            matmul_precision="highest", attention_backend="math",
            compile_mode="", batch_size=2, dtype="float32",
        ),
        TuningProfile(
            key="low_vram", label="Low VRAM",
            description="Small batches, mem-efficient attention — fits modest GPUs.",
            matmul_precision="medium", attention_backend="mem_efficient",
            compile_mode="", batch_size=1, dtype="float16",
        ),
    ]
}


@dataclass
class BenchmarkResult:
    ran_at: str
    mode: str                    # "gpu" | "cpu" | "cpu_calibration" | "unavailable"
    attention_ms: dict[str, float] = field(default_factory=dict)
    matmul_tflops: float = 0.0
    matmul_ms: float = 0.0
    matmul_label: str = "matmul 1024²"
    calibration_tokens_per_sec: float = 0.0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ran_at": self.ran_at,
            "mode": self.mode,
            "attention_ms": self.attention_ms,
            "matmul_tflops": round(self.matmul_tflops, 3),
            "matmul_ms": round(self.matmul_ms, 3),
            "matmul_label": self.matmul_label,
            "calibration_tokens_per_sec": round(self.calibration_tokens_per_sec, 1),
            "notes": self.notes,
        }


class TorchTuner:
    """Applies tuning profiles and runs micro-benchmarks. Thread-safe."""

    def __init__(self, device_info: DeviceInfo, active_profile: str = "balanced") -> None:
        self.device_info = device_info
        self.active_profile = PROFILES.get(active_profile, PROFILES["balanced"])
        self._lock = threading.Lock()
        self.last_benchmark: BenchmarkResult | None = None
        self._torch = None
        try:
            import torch  # noqa: F401
            self._torch = torch
        except Exception:  # noqa: BLE001
            self._torch = None
        self._apply_to_torch(self.active_profile)

    # ------------------------------------------------------------------ public
    def available_profiles(self) -> list[dict[str, Any]]:
        return [
            {
                "key": p.key, "label": p.label, "description": p.description,
                "matmul_precision": p.matmul_precision,
                "attention_backend": p.attention_backend,
                "compile_mode": p.compile_mode or "off",
                "batch_size": p.batch_size, "dtype": p.dtype,
                "active": p.key == self.active_profile.key,
            }
            for p in PROFILES.values()
        ]

    def set_profile(self, key: str) -> TuningProfile:
        if key not in PROFILES:
            raise KeyError(f"Unknown profile: {key}")
        with self._lock:
            self.active_profile = PROFILES[key]
            self._apply_to_torch(self.active_profile)
        return self.active_profile

    # ------------------------------------------------------------------ tuning
    def _apply_to_torch(self, profile: TuningProfile) -> None:
        """Applies the profile to torch. Matmul precision is honoured on CPU too."""
        torch = self._torch
        if torch is None:
            return
        try:
            torch.set_float32_matmul_precision(profile.matmul_precision)
        except Exception:  # noqa: BLE001
            pass

    def sdpa_kernel_ctx(self):
        """Context manager selecting the SDPA backend for the active profile.

        On CPU, "flash" has no kernel so it maps to the math backend.
        """
        torch = self._torch
        if torch is None:
            return contextlib.nullcontext()
        try:
            from torch.nn.attention import SDPBackend, sdpa_kernel

            backend = self.active_profile.attention_backend
            if backend == "flash" and not self.device_info.accelerator_available:
                backend = "math"
            mapping = {
                "flash": [SDPBackend.FLASH_ATTENTION],
                "mem_efficient": [SDPBackend.EFFICIENT_ATTENTION],
                "math": [SDPBackend.MATH],
            }
            return sdpa_kernel(mapping.get(backend, [SDPBackend.FLASH_ATTENTION]))
        except Exception:  # noqa: BLE001
            return contextlib.nullcontext()

    # -------------------------------------------------------------- benchmark
    def benchmark(self, local_synth: Callable[[str], str] | None = None,
                  warmup_text: str = "The Awam has spoken. Aam aadmi ki awaaz, "
                                     "engine ki raftaar — history in the making.") -> BenchmarkResult:
        torch = self._torch
        ran_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if torch is not None and self.device_info.accelerator_available:
            result = self._benchmark_gpu(torch, ran_at)
        elif torch is not None:
            result = self._benchmark_cpu_torch(torch, ran_at)
        elif local_synth is not None:
            result = BenchmarkResult(ran_at=ran_at, mode="cpu_calibration")
            result.notes.append("PyTorch not installed — synthesis-path calibration only.")
            result.notes.append("Install torch (CPU wheel is fine) to benchmark real kernels.")
        else:
            result = BenchmarkResult(ran_at=ran_at, mode="unavailable",
                                     notes=["No torch and no local synthesizer configured."])

        if local_synth is not None:
            self._run_calibration(result, local_synth, warmup_text)

        with self._lock:
            self.last_benchmark = result
        return result

    def _benchmark_cpu_torch(self, torch, ran_at: str) -> BenchmarkResult:
        result = BenchmarkResult(ran_at=ran_at, mode="cpu")
        batch, seq_len, heads, head_dim = 1, 256, 8, 64

        def time_fn(fn, iters: int = 10, warmup: int = 3) -> float:
            for _ in range(warmup):
                fn()
            samples = []
            for _ in range(iters):
                t0 = time.perf_counter()
                fn()
                samples.append((time.perf_counter() - t0) * 1000)
            return round(statistics.median(samples), 3)

        try:
            from torch.nn.attention import SDPBackend, sdpa_kernel

            q = torch.randn(batch, heads, seq_len, head_dim)
            k = torch.randn_like(q)
            v = torch.randn_like(q)
            for backend_name, backends in [
                ("math", [SDPBackend.MATH]),
                ("mem_efficient", [SDPBackend.EFFICIENT_ATTENTION]),
                ("flash", [SDPBackend.FLASH_ATTENTION]),
            ]:
                try:
                    with sdpa_kernel(backends):
                        ms = time_fn(lambda: torch.nn.functional.scaled_dot_product_attention(q, k, v))
                    result.attention_ms[backend_name] = ms
                except Exception:  # noqa: BLE001 — e.g. flash has no CPU kernel
                    result.attention_ms[backend_name] = None  # type: ignore[assignment]
                    result.notes.append(f"{backend_name} attention has no CPU kernel — GPU only.")
        except Exception as exc:  # noqa: BLE001
            result.notes.append(f"attention benchmark failed: {type(exc).__name__}: {exc}")

        try:
            n = 512
            a = torch.randn(n, n)
            b = torch.randn(n, n)
            result.matmul_ms = time_fn(lambda: a @ b)
            result.matmul_tflops = (2 * n**3) / (result.matmul_ms / 1000.0) / 1e12
            result.matmul_label = f"matmul {n}×{n}"
        except Exception as exc:  # noqa: BLE001
            result.notes.append(f"matmul benchmark failed: {type(exc).__name__}: {exc}")

        result.notes.append(
            f"PyTorch {torch.__version__} CPU kernels · {torch.get_num_threads()} torch threads "
            f"· profile '{self.active_profile.key}' (matmul precision "
            f"'{self.active_profile.matmul_precision}')."
        )
        return result

    def _benchmark_gpu(self, torch, ran_at: str) -> BenchmarkResult:
        result = BenchmarkResult(ran_at=ran_at, mode="gpu")
        device = "cuda:0"
        batch, seq_len, heads, head_dim = 4, 512, 16, 64
        dtype = torch.bfloat16 if self.active_profile.dtype == "bfloat16" else torch.float32

        def time_fn(fn, iters: int = 20, warmup: int = 5) -> float:
            for _ in range(warmup):
                fn()
            torch.cuda.synchronize()
            samples = []
            for _ in range(iters):
                torch.cuda.synchronize()
                t0 = time.perf_counter()
                fn()
                torch.cuda.synchronize()
                samples.append((time.perf_counter() - t0) * 1000)
            return round(statistics.median(samples), 3)

        try:
            q = torch.randn(batch, heads, seq_len, head_dim, device=device, dtype=dtype)
            k = torch.randn_like(q)
            v = torch.randn_like(q)

            from torch.nn.attention import SDPBackend, sdpa_kernel

            for backend_name, backends in [
                ("flash", [SDPBackend.FLASH_ATTENTION]),
                ("mem_efficient", [SDPBackend.EFFICIENT_ATTENTION]),
                ("math", [SDPBackend.MATH]),
            ]:
                try:
                    ctx = sdpa_kernel(backends)
                    with ctx:
                        ms = time_fn(lambda: torch.nn.functional.scaled_dot_product_attention(q, k, v))
                    result.attention_ms[backend_name] = ms
                except Exception as exc:  # noqa: BLE001
                    result.attention_ms[backend_name] = None  # type: ignore[assignment]
                    result.notes.append(f"{backend_name} attention unavailable: {type(exc).__name__}")

            a = torch.randn(1024, 1024, device=device, dtype=dtype)
            b = torch.randn(1024, 1024, device=device, dtype=dtype)
            result.matmul_ms = time_fn(lambda: a @ b)
            flops = 2 * 1024**3
            result.matmul_tflops = flops / (result.matmul_ms / 1000.0) / 1e12
            result.notes.append(f"Device: {torch.cuda.get_device_name(0)} · dtype {self.active_profile.dtype}")
        except Exception as exc:  # noqa: BLE001
            result.mode = "unavailable"
            result.notes.append(f"GPU benchmark failed: {type(exc).__name__}: {exc}")
        return result

    def _run_calibration(self, result: BenchmarkResult, synth: Callable[[str], str],
                         warmup_text: str) -> None:
        from .tokenizer import count_tokens

        synth(warmup_text)  # warm caches
        samples = []
        for _ in range(30):
            t0 = time.perf_counter()
            synth(warmup_text)
            samples.append(time.perf_counter() - t0)
        median_s = statistics.median(samples)
        tokens = count_tokens(warmup_text)
        result.calibration_tokens_per_sec = tokens / median_s if median_s else 0.0
        result.notes.append("Local synthesis-path calibration (30 samples).")
