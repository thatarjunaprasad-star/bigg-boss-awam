# 👁 Bigg Boss Awam

**The People's Oracle — an unofficial Bigg Boss AI agent** for fan votings, star ratings,
house news and trivia, powered by **AwamInfer**, a high-performance inference engine that is
ROCm-ready for AMD GPUs.

> **Disclaimer:** Bigg Boss Awam is an unofficial fan project made for entertainment.
> It is not affiliated with, endorsed by, or connected to Colors TV, Endemol Shine,
> Viacom18, or the Bigg Boss franchise. All contestants referenced are public figures;
> all news items and trivia are fan-authored fiction.

---

## What it does

| Tab | Capability |
|---|---|
| **Chat** | Converse with the Awam agent — ask for the leaderboard, cast votes in natural language (`"vote for Shehnaaz Gill"`), read the news, play trivia, or ask how the engine is doing. Warm, classy, lightly Hinglish personality. |
| **Vote** | One vote per session per 24 hours across a roster of 12 legendary contestants (winners & finalists from 18 seasons). |
| **Leaderboard** | Live ladder with podium, vote share percentages and total tally. |
| **Ratings** | 1–5 star ratings; sessions can edit their rating, averages update live. |
| **News** | Fan-feed with categories (House Pulse, Eviction Watch, Task Tracker, Style Files, Awam Polls). |
| **Trivia** | Seasoned question bank with difficulty levels, fun facts and a persistent per-session score. |
| **Engine Room** | Live diagnostics: device card, tuning profiles, paged KV-cache gauges, latency p50/p95/p99 + sparkline, throughput, micro-benchmarks. |

The same skills work through the **chat agent** and the **REST API** — the agent routes
natural-language intents (keywords + fuzzy contestant matching + per-session trivia state)
to the same data layer the UI uses.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  frontend/            vanilla-JS SPA (dark + champagne gold) │
│  chat · vote · leaderboard · ratings · news · trivia ·       │
│  engine room — 2.5 s diagnostics polling, canvas sparkline   │
└───────────────────────────┬──────────────────────────────────┘
                            │  /api/*  (X-Awam-Session header)
┌───────────────────────────▼──────────────────────────────────┐
│  backend/app                                                  │
│                                                               │
│  api/         FastAPI routers — chat, voting, content,        │
│               diagnostics (+ telemetry middleware)            │
│  agent/       AwamAgent — intent classification, grounded     │
│               response synthesis, personality                 │
│  inference/   AwamInfer engine                                │
│    · device.py     AMD ROCm (HIP) / CUDA / CPU detection      │
│    · tuner.py      PyTorch tuning profiles + micro-benchmarks │
│    · kv_cache.py   paged KV cache (vLLM-style block manager)  │
│    · engine.py     generation orchestration, remote-LLM path  │
│  data/        SQLite (WAL) + seed roster, news, trivia        │
│  core/        settings, telemetry (p50/p95/p99 ring buffers)  │
└──────────────────────────────────────────────────────────────┘
```

### The inference engine (AwamInfer)

- **Paged KV cache management** — vLLM-style block accounting: 4,096 blocks × 16 tokens,
  per-session sliding window (1,024 tokens), prefix-cache hit tracking, and LRU
  cross-session eviction that never evicts the session currently appending.
- **PyTorch tuning** — four profiles switchable live from the Engine Room:

  | Profile | Matmul precision | Attention backend | Compile | Batch | dtype |
  |---|---|---|---|---|---|
  | Throughput | high | flash | max-autotune | 8 | bf16 |
  | Balanced *(default)* | high | flash | default | 4 | bf16 |
  | Quality | highest | math | off | 2 | fp32 |
  | Low VRAM | medium | mem_efficient | off | 1 | fp16 |

  Switching a profile applies the real torch switches immediately
  (`set_float32_matmul_precision`, SDPA backend selection) — this works with the
  CPU wheel too, not just on an accelerator.

- **Diagnostics** — per-route latency ring buffers (p50/p95/p99), token throughput,
  KV-cache utilisation & hit-rate gauges, request/error counters, and micro-benchmarks.
  With PyTorch installed the **Run Benchmark** button measures real SDPA
  (math / mem-efficient / flash) attention kernels and matmul FLOPS — on a GPU via
  ROCm/CUDA, or on CPU kernels when only the CPU wheel is present. Without torch it
  falls back to an honest synthesis-path calibration.
- **Hybrid generation** — the agent always produces a grounded local synthesis from live
  data. Optionally, an **OpenAI-compatible remote LLM** (vLLM or llama.cpp on an AMD GPU,
  LM Studio, etc.) receives the conversation plus the grounded snapshot as system context
  and writes the final reply.

---

## Quick start

Requires Python 3.10+.

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS

pip install -r requirements.txt
# PyTorch (CPU wheel — powers tuning + kernel benchmarks):
pip install torch --index-url https://download.pytorch.org/whl/cpu
python run.py
```

Open **http://127.0.0.1:8000** — the SPA is served by the same process.
On first launch the SQLite database is created and seeded automatically.

> Windows console tip: if emoji output looks off, start the server with
> `set PYTHONIOENCODING=utf-8 && python run.py`.

---

## AMD GPU (ROCm) setup

The engine treats AMD as the first-class path. PyTorch (CPU wheel) is already
integrated — profiles flip real torch switches and the benchmark runs real CPU
kernels. Adding an AMD GPU upgrades the same integration to the metal:

1. **Install a ROCm (HIP) build of PyTorch** into the same environment (replaces
   the CPU wheel):

   ```bash
   # Linux
   pip install torch --index-url https://download.pytorch.org/whl/rocm6.2

   # Windows: use the HIP SDK + ROCm-enabled PyTorch wheels, e.g.
   # https://rocm.docs.amd.com/projects/install-on-windows/en/latest/
   ```

2. Restart the server. Detection is automatic — the startup banner and the Engine Room
   status pill switch to **`GPU · AMD`**, and notes will show the device, VRAM and ROCm
   version.

3. With an accelerator present, SDPA dispatches to the ROCm FlashAttention kernels
   and the **Run Benchmark** button measures full-size flash / mem-efficient / math
   attention kernels and matmul TFLOPS on the GPU.

### Optional: remote LLM endpoint

Point the engine at any OpenAI-compatible server (a great use for a beefy AMD card
running vLLM):

```bash
set AWAM_LLM_BASE_URL=http://localhost:8001/v1
set AWAM_LLM_MODEL=my-rocm-model
python run.py
```

The chat agent then sends conversation + live standings as grounded context to that
model; if the endpoint is unreachable the engine transparently falls back to local
synthesis.

---

## Configuration

All optional — sensible defaults apply.

| Env var | Default | Purpose |
|---|---|---|
| `AWAM_HOST` / `AWAM_PORT` | `127.0.0.1` / `8000` | Bind address |
| `AWAM_PROFILE` | `balanced` | Startup tuning profile |
| `AWAM_KV_NUM_BLOCKS` | `4096` | KV cache block pool size |
| `AWAM_KV_BLOCK_SIZE` | `16` | Tokens per block |
| `AWAM_KV_MAX_SESSION_TOKENS` | `1024` | Per-session sliding window |
| `AWAM_LLM_BASE_URL` | *(empty)* | OpenAI-compatible endpoint (optional) |
| `AWAM_LLM_MODEL` | `awam-local` | Model name for the remote endpoint |
| `AWAM_LLM_TIMEOUT` | `20` | Remote call timeout (seconds) |
| `AWAM_DATA_DIR` | `backend/data` | SQLite database location |
| `AWAM_FRONTEND_DIR` | `../frontend` | Static SPA directory |

---

## API reference

Session identity comes from the `X-Awam-Session` header (the SPA stores one in
localStorage); most routes also accept `session_id` in the body or query string.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/health` | Liveness + version |
| `POST` | `/api/chat` | Talk to the agent — `{ message }` → reply, intent, engine meta (tokens, TTFT, cache hit rate) |
| `GET` | `/api/chat/history` | Per-session conversation log |
| `GET` | `/api/contestants` | Full roster |
| `GET` | `/api/leaderboard` | Ranked ladder with vote share |
| `POST` | `/api/vote` | `{ contestant_id }` — one vote / session / 24 h |
| `GET` | `/api/vote-status` | Which contestant (if any) the session voted for |
| `POST` | `/api/rate` | `{ contestant_id, stars }` — new rating or edit of prior rating |
| `GET` | `/api/news?limit=20` | Fan-feed headlines |
| `GET` | `/api/trivia/next` | Next unseen question + current score |
| `POST` | `/api/trivia/answer` | `{ trivia_id, choice }` — verdict, correct answer, fun fact |
| `GET` | `/api/diagnostics` | Everything the Engine Room renders |
| `POST` | `/api/diagnostics/profile` | `{ profile }` — switch tuning profile live |
| `POST` | `/api/diagnostics/benchmark` | Run attention/matmul (or CPU calibration) benchmark |

Interactive docs: **http://127.0.0.1:8000/docs**

---

## Tests

55 tests across the KV cache, voting rules, agent intents, the PyTorch tuner
(profiles, matmul precision, CPU kernel benchmarks) and seed integrity:

```bash
cd backend
python -m unittest discover -s tests -v
```

---

## Project layout

```
backend/
  run.py                  launch script
  requirements.txt        fastapi + uvicorn (torch optional)
  app/
    main.py               FastAPI app, telemetry middleware, static mount
    runtime.py            dependency wiring
    core/                 config, telemetry
    data/                 SQLite layer + seed (roster, news, trivia)
    inference/            engine, device, tuner, kv_cache, tokenizer
    agent/                AwamAgent (intents + synthesis)
    api/                  chat, voting, content, diagnostics routers
  tests/                  kv-cache, voting, agent, seed suites
frontend/
  index.html              7-tab SPA shell
  css/style.css           dark + champagne-gold theme
  js/app.js               state, rendering, API client, diagnostics dashboard
```
