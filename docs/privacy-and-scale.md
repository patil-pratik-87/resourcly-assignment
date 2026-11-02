# Privacy and scale

Every model runs locally and all data stays on local disk, but nothing enforces that yet. At a
million similar documents the ports stay and their adapters change. Code paths are under
`src/resourcly/`.

## Privacy

| Built | Where |
| --- | --- |
| Models load only from the local cache, with `HF_HUB_OFFLINE=1` | `adapters/mlx_vlm_model.py`, `adapters/dinov2_encoder.py` |
| Uploads, requests and drawing JSON in `var/uploads/`, traces in `var/traces.sqlite` | `bootstrap.py` |
| The trace keeps the length and SHA-256 of the user's text, never the words | `agent.py`, `answers.py` |
| The server listens on `127.0.0.1`, and there is no telemetry code | `cli.py` |

| Not built | Proposal |
| --- | --- |
| No test shows a run stays offline | A test that blocks sockets during a real run |
| FastAPI's `/docs` page loads Swagger UI from a CDN | Turn it off, or serve it locally |
| No login | Authentication, and a tenant id on every record, file and trace row |
| Plain files on disk | Encryption at rest, with the customer's keys |
| No deletion | A retention period and a delete of files, record and trace |
| Offline is a code setting | No route out from the hosts; vLLM usage stats off (`VLLM_NO_USAGE_STATS=1`) |

## Scale

| Built | Where |
| --- | --- |
| `POST /api/requests` returns 202 at once; work runs in the background | `api.py`, `agent.py` |
| One job queue, routing before reading | `adapters/thread_jobs.py` |
| Cheap router layers first: rules decide 5.9% of files, the probe 91.2%, Qwen3-VL 8B 2.9% | `research/routing/README.md` |
| Stores, queue and models behind ports | `ports.py` |

| Today | At scale | Why |
| --- | --- | --- |
| MLX on one Mac | vLLM 0.11 or later, one Qwen3-VL 8B per GPU; SGLang as the alternative | Continuous batching; prefix caching reuses only blocks before the image, so the prompt goes first; JSON schema output |
| One thread | A queue (Redis or SQS), workers with retries and priorities, one job per page | Survives restarts, spreads over machines |
| Files and SQLite | Object storage and Postgres | Listing requests today reads every `request.json` |
| Brute force over 46 figures | FAISS or pgvector HNSW behind the same port | Approximate search over millions of figures |
| Every file read in full | A content-hash cache, and template reuse across look-alike drawings | "All very alike": a family shares frame, title block and notes |
| A fixed eval set | Sampled evals in production, alerts when route shares or values per page drift | The trace stores both |

## Estimate per million pages

This is an estimate. Measured on an M1 Pro, `vector-crop-v1` takes 64 s per page and Qwen3-VL 8B 5 s
per crop, so about 13 calls per page (at most 33, one per value). Assumed: 3.3 requests per second
per A100, from vLLM's only published example near this model (Qwen2.5-VL-7B, 13.09 on 4 A100s),
and $2 per A100 hour.

| | One Mac, measured | vLLM on A100s, estimate |
| --- | --- | --- |
| Per page | 64 s | 4 to 10 GPU seconds |
| A million pages | 17,800 hours, about 2 years | 1,100 to 2,800 GPU hours, $2,200 to $5,600 |

Cache hits lower it. Benchmark real crops on the target GPU before buying hardware.

Sources: vLLM [models](https://docs.vllm.ai/en/latest/models/supported_models.html),
[Qwen3-VL](https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen3-VL.html),
[Qwen2.5-VL](https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen2.5-VL.html),
[prefix caching](https://docs.vllm.ai/en/latest/design/prefix_caching.html),
[structured outputs](https://docs.vllm.ai/en/latest/features/structured_outputs.html),
[usage stats](https://docs.vllm.ai/en/latest/usage/usage_stats.html);
[SGLang](https://docs.sglang.io/docs/advanced_features/structured_outputs).
