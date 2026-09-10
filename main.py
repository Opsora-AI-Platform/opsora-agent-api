"""Opsora Agent API — OpenAI-compatible proxy backed by NVIDIA NIM."""

from __future__ import annotations

import hmac
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("opsora")


class RateLimiter:
    def __init__(self, rpm: int) -> None:
        self.rpm = max(1, rpm)
        self._windows: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str) -> bool:
        now = time.time()
        cutoff = now - 60
        window = [t for t in self._windows[key] if t > cutoff]
        if len(window) >= self.rpm:
            self._windows[key] = window
            return False
        window.append(now)
        self._windows[key] = window
        return True


limiter = RateLimiter(config.RATE_LIMIT_RPM)
client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global client
    if not config.NVIDIA_API_KEY:
        raise RuntimeError("NVIDIA_API_KEY environment variable is required")
    client = httpx.AsyncClient(
        base_url=config.NVIDIA_BASE_URL,
        headers={
            "Authorization": f"Bearer {config.NVIDIA_API_KEY}",
            "Content-Type": "application/json",
        },
        timeout=httpx.Timeout(config.UPSTREAM_TIMEOUT, connect=10.0),
    )
    logger.info("Opsora Agent API started — upstream %s", config.NVIDIA_BASE_URL)
    try:
        yield
    finally:
        if client is not None:
            await client.aclose()
        client = None


app = FastAPI(title="Opsora Agent API", version="1.0.0", lifespan=lifespan)


def _extract_bearer(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        if token:
            return token
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": {"message": "Missing or invalid Authorization header.", "type": "auth_error"}},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _authenticate(request: Request) -> str:
    """Fail closed: production must never become anonymous because a key is missing."""
    token = _extract_bearer(request)
    if not config.OPSORA_API_KEYS:
        logger.error("OPSORA_API_KEYS is empty — refusing authenticated API traffic")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"message": "API authentication is not configured.", "type": "configuration_error"}},
        )
    if not any(hmac.compare_digest(token, configured) for configured in config.OPSORA_API_KEYS):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"message": "Invalid API key.", "type": "auth_error"}},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def _check_rate_limit(key: str) -> None:
    if not limiter.allow(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {"message": "Rate limit exceeded. Try again later.", "type": "rate_limit_error"}},
        )


def _resolve_model(requested: str) -> str:
    return config.MODEL_MAP.get(requested, requested)


def _opsora_headers() -> dict[str, str]:
    return {"X-Powered-By": "Opsora Agent API"}


def _strip_internal_keys(body: dict[str, Any]) -> dict[str, Any]:
    body.pop("user", None)
    return body


def _log_request(method: str, path: str, model: str, stream: bool) -> None:
    logger.info("→ %s %s model=%s stream=%s", method, path, model, stream)


def _log_response(path: str, status_code: int, elapsed: float) -> None:
    logger.info("← %s status=%s elapsed=%.2fs", path, status_code, elapsed)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "opsora-agent-api"}


@app.get("/v1/models")
async def list_models(request: Request):
    _authenticate(request)
    models = [
        {"id": alias, "object": "model", "created": int(time.time()), "owned_by": "opsora", "permission": []}
        for alias in config.MODEL_MAP
    ]
    return JSONResponse(content={"object": "list", "data": models}, headers=_opsora_headers())


async def _proxy_completion(request: Request, path: str) -> JSONResponse | StreamingResponse:
    api_key = _authenticate(request)
    _check_rate_limit(api_key)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail={"error": {"message": "Invalid JSON body.", "type": "invalid_request_error"}})
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail={"error": {"message": "Request body must be an object.", "type": "invalid_request_error"}})

    requested_model = str(body.get("model", "opsora-brain"))
    body["model"] = _resolve_model(requested_model)
    body = _strip_internal_keys(body)
    stream = bool(body.get("stream", False))
    _log_request("POST", path, requested_model, stream)
    t0 = time.time()

    try:
        if stream:
            return await _stream_upstream(path, body, t0)
        return await _non_stream_upstream(path, body, t0)
    except httpx.TimeoutException:
        _log_response(path, 504, time.time() - t0)
        raise HTTPException(status_code=504, detail={"error": {"message": "Upstream request timed out.", "type": "timeout_error"}})
    except httpx.HTTPError:
        _log_response(path, 502, time.time() - t0)
        raise HTTPException(status_code=502, detail={"error": {"message": "Upstream service error.", "type": "upstream_error"}})


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    return await _proxy_completion(request, "/chat/completions")


@app.post("/v1/completions")
async def completions(request: Request):
    return await _proxy_completion(request, "/completions")


async def _non_stream_upstream(path: str, body: dict[str, Any], t0: float) -> JSONResponse:
    if client is None:
        raise HTTPException(status_code=503, detail={"error": {"message": "Upstream client is not ready.", "type": "configuration_error"}})
    resp = await client.post(path, json=body)
    _log_response(path, resp.status_code, time.time() - t0)
    if resp.status_code != 200:
        logger.error("Upstream %s returned %s: %s", path, resp.status_code, resp.text[:500])
        return JSONResponse(
            status_code=resp.status_code,
            content={"error": {"message": f"Upstream error: {resp.status_code}", "type": "upstream_error"}},
            headers=_opsora_headers(),
        )
    return JSONResponse(content=resp.json(), headers=_opsora_headers())


async def _stream_upstream(path: str, body: dict[str, Any], t0: float) -> StreamingResponse:
    if client is None:
        raise HTTPException(status_code=503, detail={"error": {"message": "Upstream client is not ready.", "type": "configuration_error"}})
    req = client.build_request("POST", path, json=body)
    resp = await client.send(req, stream=True)
    if resp.status_code != 200:
        body_text = await resp.aread()
        await resp.aclose()
        _log_response(path, resp.status_code, time.time() - t0)
        logger.error("Upstream %s stream returned %s: %s", path, resp.status_code, body_text[:500])
        return JSONResponse(
            status_code=resp.status_code,
            content={"error": {"message": f"Upstream error: {resp.status_code}", "type": "upstream_error"}},
            headers=_opsora_headers(),
        )

    async def event_generator():
        try:
            async for line in resp.aiter_lines():
                if line:
                    yield line + "\n"
        finally:
            await resp.aclose()
            _log_response(path, 200, time.time() - t0)

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=_opsora_headers())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, log_level="info")
