"""Runtime assembly — singletons shared across the API layer."""
from __future__ import annotations

from dataclasses import dataclass

from .agent.awam import AwamAgent
from .core.config import Settings
from .core.telemetry import TelemetryService
from .data.db import Database
from .data.seed import seed
from .inference.device import DeviceInfo, detect_device
from .inference.engine import AwamInferEngine
from .inference.kv_cache import PagedKVCacheManager
from .inference.tuner import TorchTuner


@dataclass
class Runtime:
    settings: Settings
    db: Database
    telemetry: TelemetryService
    device: DeviceInfo
    kv_cache: PagedKVCacheManager
    tuner: TorchTuner
    engine: AwamInferEngine
    agent: AwamAgent


def build_runtime(settings: Settings) -> Runtime:
    db = Database(settings.db_path)
    seed(db)

    telemetry = TelemetryService(window=settings.telemetry_window)
    device = detect_device()
    kv_cache = PagedKVCacheManager(
        num_blocks=settings.kv_num_blocks,
        block_size=settings.kv_block_size,
        max_session_tokens=settings.kv_max_session_tokens,
    )
    tuner = TorchTuner(device, active_profile=settings.default_profile)

    # Placeholder engine/agent created first so they can reference each other.
    engine = AwamInferEngine(
        local_synth=lambda session_id, message: ("", ""),
        device_info=device,
        kv_cache=kv_cache,
        tuner=tuner,
    )
    agent = AwamAgent(db, engine, telemetry, vote_cooldown_hours=settings.vote_cooldown_hours)
    engine._local_synth = agent.respond  # wire the real synthesizer  # noqa: SLF001

    if settings.llm_base_url:
        engine._llm_base_url = settings.llm_base_url.rstrip("/")  # noqa: SLF001
        engine._llm_model = settings.llm_model  # noqa: SLF001
        engine._llm_timeout_s = settings.llm_timeout_s  # noqa: SLF001
    engine._system_prompt_builder = agent.live_context  # noqa: SLF001

    return Runtime(
        settings=settings,
        db=db,
        telemetry=telemetry,
        device=device,
        kv_cache=kv_cache,
        tuner=tuner,
        engine=engine,
        agent=agent,
    )
