"""Тесты GPU/CPU-бэкендов и BackendRouter (T-144)."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any, cast

import httpx
import pytest
from prometheus_client import generate_latest

from app.backends import CpuLlamaBackend, GpuHttpBackend
from app.metrics import record_backend_request, record_backend_ttft
from app.router import GPU_FAILURE_THRESHOLD, BackendRouter
from app.settings import AppSettings


def _settings(**overrides: Any) -> AppSettings:
    defaults: dict[str, Any] = {
        "gpu_backend_enabled": True,
        "gpu_backend_base": "http://gpu.test/v1",
        "gpu_backend_api_key": "secret",
        "gpu_backend_model": "qwen3-8b-vet@q4_k_m",
        "gpu_backend_probe_interval_s": 15.0,
        "gpu_backend_probe_timeout_s": 0.5,
        "gpu_backend_ttft_fallback_s": 0.5,
    }
    defaults.update(overrides)
    return AppSettings(_env_file=None, **defaults)


def test_gpu_settings_are_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VET_API_GPU_BACKEND_ENABLED", "true")
    monkeypatch.setenv("VET_API_GPU_BACKEND_BASE", "http://gpu:8034/v1")
    monkeypatch.setenv("VET_API_GPU_BACKEND_API_KEY", "secret")
    monkeypatch.setenv("VET_API_GPU_BACKEND_PROBE_INTERVAL_S", "12")

    settings = AppSettings(_env_file=None)

    assert settings.gpu_backend_enabled is True
    assert settings.gpu_backend_base == "http://gpu:8034/v1"
    assert settings.gpu_backend_api_key == "secret"
    assert settings.gpu_backend_probe_interval_s == 12.0


class FakeGpu:
    name = "gpu"

    def __init__(
        self,
        *,
        probe_ok: bool = True,
        fail_create: bool = False,
        chunks: list[str] | None = None,
        fail_stream_before_first: bool = False,
        fail_stream_after_first: bool = False,
    ) -> None:
        self.probe_ok = probe_ok
        self.fail_create = fail_create
        self.chunks = chunks or ["gpu"]
        self.fail_stream_before_first = fail_stream_before_first
        self.fail_stream_after_first = fail_stream_after_first
        self.probe_calls = 0
        self.create_calls = 0

    async def probe(self) -> bool:
        self.probe_calls += 1
        return self.probe_ok

    async def create_chat_completion(self, **kwargs: Any) -> dict[str, Any]:
        self.create_calls += 1
        if self.fail_create:
            raise RuntimeError("gpu down")
        return {"choices": [{"message": {"content": "gpu"}}]}

    async def stream_chat_completion(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        if self.fail_stream_before_first:
            raise RuntimeError("gpu stream down")
        for index, text in enumerate(self.chunks):
            if index == 1 and self.fail_stream_after_first:
                raise RuntimeError("gpu stream broke")
            yield {"choices": [{"index": 0, "delta": {"content": text}}]}

    async def aclose(self) -> None:
        return None


class FakeCpu:
    name = "cpu"

    def __init__(self, chunks: list[str] | None = None) -> None:
        self.chunks = chunks or ["cpu"]
        self.create_calls = 0

    async def probe(self) -> bool:
        return True

    async def create_chat_completion(self, **kwargs: Any) -> dict[str, Any]:
        self.create_calls += 1
        return {"choices": [{"message": {"content": "cpu"}}]}

    async def stream_chat_completion(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        for text in self.chunks:
            yield {"choices": [{"index": 0, "delta": {"content": text}}]}

    async def aclose(self) -> None:
        return None


def _router(gpu: FakeGpu, cpu: FakeCpu | None = None) -> BackendRouter:
    return BackendRouter(
        gpu=cast(Any, gpu),
        cpu=cast(Any, cpu or FakeCpu()),
        settings=_settings(),
    )


async def test_gpu_probe_uses_models_endpoint_and_auth() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json={"data": [{"id": "qwen3-8b-vet@q4_k_m"}]})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        backend = GpuHttpBackend(_settings(), client=http_client)
        assert await backend.probe() is True

    assert captured == {"path": "/v1/models", "auth": "Bearer secret"}


async def test_gpu_probe_failure_returns_false() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503))

    async with httpx.AsyncClient(transport=transport) as http_client:
        backend = GpuHttpBackend(_settings(), client=http_client)
        assert await backend.probe() is False


async def test_gpu_chat_posts_openai_payload() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Ответ"}}]},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        backend = GpuHttpBackend(_settings(), client=http_client)
        result = await backend.create_chat_completion(
            messages=[{"role": "user", "content": "Вопрос"}],
            temperature=0.2,
        )

    assert result["choices"][0]["message"]["content"] == "Ответ"
    assert captured["path"] == "/v1/chat/completions"
    assert captured["payload"]["model"] == "qwen3-8b-vet@q4_k_m"
    assert captured["payload"]["messages"] == [{"role": "user", "content": "Вопрос"}]


async def test_gpu_stream_parses_sse_chunks() -> None:
    body = (
        'data: {"choices":[{"index":0,"delta":{"content":"При"}}]}\n\n'
        'data: {"choices":[{"index":0,"delta":{"content":"вет"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))

    async with httpx.AsyncClient(transport=transport) as http_client:
        backend = GpuHttpBackend(_settings(), client=http_client)
        chunks = [
            chunk
            async for chunk in backend.stream_chat_completion(
                messages=[{"role": "user", "content": "Вопрос"}],
            )
        ]

    assert [chunk["choices"][0]["delta"]["content"] for chunk in chunks] == [
        "При",
        "вет",
    ]


async def test_gpu_stream_requests_usage_in_stream_options() -> None:
    """T-138.5: без include_usage LM Studio не отдаёт usage в стриме."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, content="data: [DONE]\n\n")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        backend = GpuHttpBackend(_settings(), client=http_client)
        async for _chunk in backend.stream_chat_completion(
            messages=[{"role": "user", "content": "Вопрос"}],
        ):
            pass

    assert captured["payload"]["stream"] is True
    assert captured["payload"]["stream_options"] == {"include_usage": True}


async def test_gpu_stream_passes_usage_from_last_chunk() -> None:
    """T-138: если LM Studio прислал usage, бэкенд отдаёт его без потерь."""
    body = (
        'data: {"choices":[{"index":0,"delta":{"content":"Ответ"}}]}\n\n'
        'data: {"choices":[],"usage":'
        '{"prompt_tokens":10,"completion_tokens":4,"total_tokens":14}}\n\n'
        "data: [DONE]\n\n"
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))

    async with httpx.AsyncClient(transport=transport) as http_client:
        backend = GpuHttpBackend(_settings(), client=http_client)
        chunks = [
            chunk
            async for chunk in backend.stream_chat_completion(
                messages=[{"role": "user", "content": "Вопрос"}],
            )
        ]

    assert chunks[-1]["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 4,
        "total_tokens": 14,
    }


async def test_cpu_stream_reports_usage_from_n_tokens() -> None:
    """T-138: CPU-стрим считает prompt/completion по n_tokens и tokenizer."""

    class TokenModel:
        def __init__(self) -> None:
            self.n_tokens = 0

        def tokenize(self, text: str | bytes, add_bos: bool = False) -> list[str]:
            if isinstance(text, bytes):
                text = text.decode("utf-8")
            return text.split()

        def create_chat_completion(self, **kwargs: Any) -> Any:
            def stream() -> Any:
                # Префилл prompt: 12 токенов, затем два сгенерированных.
                self.n_tokens = 12
                for text in ("Один ", "два"):
                    self.n_tokens += len(text.split())
                    yield {
                        "choices": [
                            {"index": 0, "delta": {"content": text}}
                        ]
                    }

            return stream()

    backend = CpuLlamaBackend(model=TokenModel())
    chunks = [
        chunk
        async for chunk in backend.stream_chat_completion(
            messages=[{"role": "user", "content": "Вопрос"}],
        )
    ]

    assert chunks[-1]["choices"] == []
    assert chunks[-1]["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 2,
        "total_tokens": 14,
    }


async def test_router_prefers_gpu_after_successful_probe() -> None:
    gpu = FakeGpu()
    router = _router(gpu)

    assert await router.probe_once() is True
    assert router.active_backend_name == "gpu"

    result = await router.create_chat_completion(messages=[])
    assert result["choices"][0]["message"]["content"] == "gpu"


async def test_router_falls_back_to_cpu_and_opens_circuit_breaker() -> None:
    gpu = FakeGpu(fail_create=True)
    cpu = FakeCpu()
    router = _router(gpu, cpu)
    assert await router.probe_once() is True

    for _ in range(GPU_FAILURE_THRESHOLD):
        result = await router.create_chat_completion(messages=[])
        assert result["choices"][0]["message"]["content"] == "cpu"

    assert router.active_backend_name == "cpu"
    assert router.gpu_available is False
    assert cpu.create_calls == GPU_FAILURE_THRESHOLD


async def test_router_stream_falls_back_before_first_chunk() -> None:
    gpu = FakeGpu(fail_stream_before_first=True)
    cpu = FakeCpu(chunks=["cpu"])
    router = _router(gpu, cpu)
    assert await router.probe_once() is True

    chunks = [
        chunk
        async for chunk in router.stream_chat_completion(messages=[])
    ]

    assert [chunk["choices"][0]["delta"]["content"] for chunk in chunks] == ["cpu"]


async def test_router_does_not_fallback_after_partial_stream() -> None:
    gpu = FakeGpu(chunks=["a", "b"], fail_stream_after_first=True)
    cpu = FakeCpu(chunks=["cpu"])
    router = _router(gpu, cpu)
    assert await router.probe_once() is True

    with pytest.raises(RuntimeError, match="gpu stream broke"):
        async for _ in router.stream_chat_completion(messages=[]):
            pass

    assert cpu.create_calls == 0


async def test_router_probe_skips_gpu_during_cooldown() -> None:
    gpu = FakeGpu(fail_create=True)
    router = _router(gpu)
    assert await router.probe_once() is True

    for _ in range(GPU_FAILURE_THRESHOLD):
        await router.create_chat_completion(messages=[])

    calls_before = gpu.probe_calls
    assert await router.probe_once() is False
    assert gpu.probe_calls == calls_before
    assert router.active_backend_name == "cpu"
    assert time.monotonic() < router._cooldown_until


def test_backend_metrics_are_exported() -> None:
    record_backend_request("gpu", "success")
    record_backend_ttft("gpu", 0.1)

    body = generate_latest().decode("utf-8")

    assert "vet_llm_backend_requests_total" in body
    assert "vet_llm_backend_ttft_seconds" in body
