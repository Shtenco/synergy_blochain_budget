from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


class EISSOIUnavailable(RuntimeError):
    """Raised when the registered EIS SOI client is unavailable or misconfigured."""


_FORBIDDEN_SECRET_KEYS = {
    "token", "password", "secret", "access_key", "secret_key", "private_key", "client_secret"
}
_ALLOWED_METHODS = {"getNsiRequest", "getDocsByReestrNumberRequest", "getDocsByOrgRegionRequest"}


def _reject_embedded_secrets(value: Any, path: str = "request") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).strip().lower() in _FORBIDDEN_SECRET_KEYS:
                raise ValueError(f"secret field is forbidden in SOI request plan: {path}.{key}")
            _reject_embedded_secrets(child, f"{path}.{key}")
    elif isinstance(value, list):
        for i, child in enumerate(value):
            _reject_embedded_secrets(child, f"{path}[{i}]")


def load_request_plan(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text("utf-8"))
    requests = raw.get("requests", raw if isinstance(raw, list) else [])
    if not isinstance(requests, list):
        raise ValueError("SOI request plan must contain a list named 'requests'")
    out: list[dict[str, Any]] = []
    for i, request in enumerate(requests):
        if not isinstance(request, dict):
            raise ValueError(f"SOI request #{i} must be an object")
        _reject_embedded_secrets(request, f"requests[{i}]")
        method = str(request.get("method") or "")
        kwargs = request.get("kwargs") or {}
        if method not in _ALLOWED_METHODS:
            raise ValueError(f"unsupported SOI method {method!r}; allowed: {sorted(_ALLOWED_METHODS)}")
        if not isinstance(kwargs, dict):
            raise ValueError(f"SOI request #{i} kwargs must be an object")
        out.append({"method": method, "kwargs": kwargs})
    return out


def _client(sender: str = "sinergy-budget"):
    try:
        import dars  # type: ignore
    except ImportError as exc:
        raise EISSOIUnavailable("install optional extra 'eis' (dars) on a registered EIS data node") from exc
    factory = getattr(dars, "client", None)
    if not callable(factory):
        raise EISSOIUnavailable("installed dars package does not expose the documented dars.client(...) API")
    try:
        return factory(sender=sender)
    except Exception as exc:
        raise EISSOIUnavailable(f"cannot initialize EIS SOI client: {exc}") from exc


def execute_request_plan(requests: Iterable[dict[str, Any]], *, sender: str = "sinergy-budget") -> list[dict[str, Any]]:
    client = _client(sender=sender)
    results: list[dict[str, Any]] = []
    for i, request in enumerate(requests):
        _reject_embedded_secrets(request, f"requests[{i}]")
        method_name = str(request.get("method") or "")
        if method_name not in _ALLOWED_METHODS:
            raise ValueError(f"unsupported SOI method: {method_name}")
        kwargs = request.get("kwargs") or {}
        method = getattr(client, method_name, None)
        if not callable(method):
            raise EISSOIUnavailable(f"dars client does not expose {method_name}")
        result = method(**kwargs)
        results.append({"method": method_name, "kwargs": kwargs, "result": result})
    return results


def download_nsi(*, base: str, nsicode: str, prefix: str, sender: str = "sinergy-budget") -> Any:
    client = _client(sender=sender)
    method = getattr(client, "getNsiRequest", None)
    if not callable(method):
        raise EISSOIUnavailable("dars client does not expose getNsiRequest")
    return method(base=base, nsicode=nsicode, prefix=prefix)
