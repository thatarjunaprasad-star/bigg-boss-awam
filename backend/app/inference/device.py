"""Hardware detection: AMD ROCm (HIP) first-class, CUDA passthrough, CPU fallback."""
from __future__ import annotations

import platform
from dataclasses import dataclass, field


@dataclass
class DeviceInfo:
    backend: str            # "rocm" | "cuda" | "cpu"
    vendor: str             # "AMD" | "NVIDIA" | "CPU"
    name: str
    torch_version: str = ""
    rocm_version: str = ""
    compute_units: int = 0
    accelerator_available: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        if self.accelerator_available:
            return f"{self.vendor} · {self.name}"
        return "CPU Precision Mode"

    def as_dict(self) -> dict:
        return {
            "backend": self.backend,
            "vendor": self.vendor,
            "name": self.name,
            "label": self.label,
            "torch_version": self.torch_version,
            "rocm_version": self.rocm_version,
            "compute_units": self.compute_units,
            "accelerator_available": self.accelerator_available,
            "notes": self.notes,
        }


def detect_device() -> DeviceInfo:
    notes: list[str] = []
    try:
        import torch
    except Exception as exc:  # noqa: BLE001 — torch is optional
        notes.append(f"PyTorch not installed ({type(exc).__name__}) — running CPU precision mode.")
        notes.append("Install a ROCm build of PyTorch to light up the AMD GPU path.")
        return DeviceInfo(
            backend="cpu",
            vendor="CPU",
            name=f"{platform.processor() or platform.machine()} · Python {platform.python_version()}",
            notes=notes,
        )

    torch_version = getattr(torch, "__version__", "unknown")
    hip_version = getattr(torch.version, "hip", None)
    rocm_version = hip_version or ""

    try:
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            if hip_version:
                vendor = "AMD"
                backend = "rocm"
                notes.append("ROCm/HIP PyTorch build detected — flash SDPA & tuned matmul enabled.")
            else:
                vendor = "NVIDIA"
                backend = "cuda"
                notes.append("CUDA device detected (AMD path prefers a ROCm/HIP build).")
            total_mem = 0
            try:
                props = torch.cuda.get_device_properties(0)
                total_mem = getattr(props, "total_memory", 0)
                if total_mem:
                    notes.append(f"VRAM: {total_mem / 1024**3:.1f} GiB")
            except Exception:  # noqa: BLE001
                pass
            return DeviceInfo(
                backend=backend,
                vendor=vendor,
                name=name,
                torch_version=torch_version,
                rocm_version=rocm_version,
                accelerator_available=True,
                notes=notes,
            )
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Accelerator probe failed: {type(exc).__name__}: {exc}")

    notes.append("No accelerator visible to PyTorch — CPU precision mode engaged.")
    notes.append(f"PyTorch {torch_version} ready — matmul precision tuning and "
                 "SDPA/matmul kernel benchmarks run on CPU.")
    notes.append("Install a ROCm (HIP) build of PyTorch to light up the AMD GPU path.")
    return DeviceInfo(
        backend="cpu",
        vendor="CPU",
        name=f"{platform.processor() or platform.machine()} · torch {torch_version}",
        torch_version=torch_version,
        notes=notes,
    )
