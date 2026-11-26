import hashlib
import json
import logging
from collections.abc import Callable
from http.client import HTTPException as HTTPProtocolError
from ipaddress import ip_address
from time import monotonic
from typing import BinaryIO, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener
from urllib.request import Request as URLRequest

from app.core.config import DEFAULT_ANALYSIS_OUTPUT_TOKENS, AnalysisProfile, Settings
from app.core.errors import AppError
from app.integrations import input_estimate, response_errors
from app.integrations.call_control import connected
from app.integrations.response_diagnostics import (
    EVENTS,
    USAGE_KEYS,
    error_metadata,
    safe_identifier,
    safe_snapshot,
)
from app.integrations.response_input import prepare_messages

ReasoningEffort = Literal[
    "default", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"
]
logger = logging.getLogger(__name__)


def normalize_base_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.port not in (None, 443)
        or parts.query
        or parts.fragment
    ):
        raise ValueError("invalid_base_url")
    hostname = parts.hostname.lower()
    try:
        address = ip_address(hostname)
    except ValueError:
        address = None
    if (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or (address is not None and not address.is_global)
        or any(segment in (".", "..") for segment in parts.path.split("/"))
    ):
        raise ValueError("invalid_base_url")
    path = parts.path.rstrip("/")
    return urlunsplit(("https", parts.hostname.lower(), path, "", ""))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe_model(
    base_url: str, model: str, key: str, reasoning_effort: ReasoningEffort = "default"
) -> None:
    payload = {
        "model": model,
        "input": "请只回复 OK",
        "store": False,
        "max_output_tokens": 256,
        "stream": False,
    }
    if reasoning_effort != "default":
        payload["reasoning"] = {"effort": reasoning_effort}
    send_response(base_url, key, payload, 120, 262144)


def list_models(base_url: str, key: str) -> list[str]:
    request = URLRequest(
        base_url + "/models",
        headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
        method="GET",
    )
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=15) as response:
            body = response.read(262145)
    except HTTPError as exc:
        code = {
            401: "ai_auth_failed",
            403: "ai_access_denied",
            404: "ai_models_unavailable",
            429: "ai_quota_or_rate_limit",
        }.get(exc.code, "ai_upstream_error")
        exc.close()
        raise AppError(502, code) from None
    except TimeoutError:
        raise AppError(504, "ai_timeout") from None
    except (URLError, OSError, HTTPProtocolError):
        raise AppError(502, "ai_connection_failed") from None
    try:
        if len(body) > 262144:
            raise ValueError
        result = json.loads(body)
        if (
            not isinstance(result, dict)
            or result.get("object") != "list"
            or not isinstance(result.get("data"), list)
        ):
            raise ValueError
        if any(
            not isinstance(item, dict) or not isinstance(item.get("id"), str)
            for item in result["data"]
        ):
            raise ValueError
        models = [item["id"] for item in result["data"]]
        if len(models) > 1000 or any(
            not model or len(model) > 160 or any(ord(char) < 32 for char in model)
            for model in models
        ):
            raise ValueError
        return sorted(set(models), key=str.casefold)
    except (ValueError, UnicodeError):
        raise AppError(502, "ai_invalid_response") from None


def analyze(
    base_url: str,
    model: str,
    key: str,
    effort: ReasoningEffort,
    instructions: str,
    content: list[dict],
    *,
    instruction_messages: list[dict] | None = None,
    diagnostics: dict | None = None,
    on_progress: Callable[[], None] | None = None,
    output_profile: AnalysisProfile | None = None,
) -> str:
    output_limit = DEFAULT_ANALYSIS_OUTPUT_TOKENS
    if output_profile is not None:
        output_limit = Settings().ai_analysis_max_output_tokens.get(output_profile, output_limit)
    return _model_response(
        base_url,
        model,
        key,
        effort,
        instructions,
        [*(instruction_messages or []), {"role": "user", "content": content}],
        max_output_tokens=output_limit,
        response_limit=16 * 1024 * 1024,
        diagnostics=diagnostics,
        on_progress=on_progress,
    )


def converse(
    base_url,
    model,
    key,
    effort,
    instructions,
    messages,
    *,
    diagnostics: dict | None = None,
    on_progress=None,
):
    return _model_response(
        base_url,
        model,
        key,
        effort,
        instructions,
        messages,
        max_output_tokens=8192,
        response_limit=4 * 1024 * 1024,
        diagnostics=diagnostics,
        on_progress=on_progress,
    )


def _model_response(
    base_url,
    model,
    key,
    effort,
    instructions,
    messages,
    *,
    max_output_tokens,
    response_limit,
    diagnostics=None,
    on_progress=None,
):
    messages, transport_note, metrics = prepare_messages(messages)
    stats = diagnostics if diagnostics is not None else {}
    stats.update(metrics)
    stats["input_estimate"] = input_estimate.estimate(instructions + transport_note, messages)
    payload = {
        "model": model,
        "instructions": instructions + transport_note,
        "input": messages,
        "store": False,
        "stream": True,
        "max_output_tokens": max_output_tokens,
    }
    if effort != "default":
        payload["reasoning"] = {"effort": effort}
    return send_response(
        base_url,
        key,
        payload,
        None,
        response_limit,
        diagnostics=stats,
        on_progress=on_progress,
    )


def read_stream(
    response: BinaryIO,
    limit: int,
    started: float,
    *,
    diagnostics: dict | None = None,
    on_progress: Callable[[], None] | None = None,
    secret: str = "",
) -> dict:
    """Only a completed Responses event is a result, never accumulated partial deltas."""
    total, data = 0, []
    stats = diagnostics if diagnostics is not None else {}
    while True:
        raw = response.readline(limit - total + 1)
        if not raw:
            stats["termination"] = "eof_without_completed"
            raise AppError(502, "ai_incomplete_response")
        if total == 0:
            stats["first_byte_seconds"] = round(monotonic() - started, 3)
            logger.info("AI response stream_started elapsed_seconds=%.1f", monotonic() - started)
        total += len(raw)
        stats["received_bytes"] = total
        stats["last_activity_seconds"] = round(monotonic() - started, 3)
        stats["phase"] = "receiving"
        if total > limit:
            stats["termination"] = "response_size_limit"
            raise AppError(502, "ai_invalid_response")
        line = raw.decode("utf-8-sig" if total == len(raw) else "utf-8").rstrip("\r\n")
        if line.startswith(":"):
            stats["heartbeats"] = stats.get("heartbeats", 0) + 1
        if line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
        elif not line and data:
            body = "\n".join(data)
            data = []
            if body.strip() == "[DONE]":
                stats["termination"] = "done_without_completed"
                raise AppError(502, "ai_incomplete_response")
            event = json.loads(body)
            if not isinstance(event, dict):
                raise AppError(502, "ai_invalid_response")
            kind = event.get("type")
            name = kind if isinstance(kind, str) and kind in EVENTS else "other"
            counts = stats.setdefault("events", {})
            counts[name] = counts.get(name, 0) + 1
            stats["last_event"] = name
            event_request_id = safe_identifier(event.get("request_id"), secret)
            if event_request_id:
                stats["request_id"] = event_request_id
            stats.setdefault("first_event_seconds", round(monotonic() - started, 3))
            result = event.get("response")
            if isinstance(result, dict):
                response_id = safe_identifier(result.get("id"), secret)
                if response_id:
                    stats["response_id"] = response_id
            if kind == "response.output_text.delta" and isinstance(event.get("delta"), str):
                stats["output_characters"] = stats.get("output_characters", 0) + len(event["delta"])
            if kind == "response.completed":
                result = event.get("response")
                if not isinstance(result, dict):
                    raise AppError(502, "ai_invalid_response")
                stats["termination"] = "response.completed"
                return result
            if kind == "response.incomplete":
                stats.update(error_metadata(event), termination="response.incomplete")
                stats["elapsed_seconds"] = round(monotonic() - started, 3)
                response_errors.capture(body.encode(), stats, secret)
                raise AppError(502, "ai_incomplete_response")
            if kind in ("error", "response.failed"):
                stats.update(error_metadata(event), termination=kind)
                stats["elapsed_seconds"] = round(monotonic() - started, 3)
                response_errors.capture(body.encode(), stats, secret)
                code = (
                    "ai_upstream_account_unavailable"
                    if stats.get("error_category") == "account_unavailable"
                    else "ai_stream_failed"
                )
                raise AppError(502, code)
            if kind in ("response.refusal.delta", "response.refusal.done"):
                stats["termination"] = "response.refusal"
                raise AppError(502, "ai_refused")
        if on_progress:
            on_progress()


def response_error_code(status: int, stats: dict) -> str:
    code = {
        401: "ai_auth_failed",
        403: "ai_access_denied",
        404: "ai_model_or_endpoint_unavailable",
        413: "ai_input_too_large",
        429: "ai_quota_or_rate_limit",
        502: "ai_gateway_error",
        503: "ai_service_unavailable",
        504: "ai_gateway_timeout",
    }.get(status, "ai_upstream_error")
    if status in (400, 422):
        code = {
            "context_limit": "ai_context_limit",
            "input_limit": "ai_input_too_large",
            "output_limit": "ai_output_limit",
            "model_unavailable": "ai_model_or_endpoint_unavailable",
            "parameters": "ai_parameters_rejected",
        }.get(stats.get("error_category"), "ai_request_rejected")
    if status in (400, 422, 503) and stats.get("error_category") == "account_unavailable":
        code = "ai_upstream_account_unavailable"
    return code


def model_request(base_url: str, key: str, payload: dict) -> URLRequest:
    return URLRequest(
        base_url + "/responses",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if payload.get("stream") else "application/json",
        },
        method="POST",
    )


def open_model_response(request: URLRequest, timeout: int | float | None):
    """Shared fixed Responses transport, including the bounded CLI connection probe."""
    return build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout)


def usage_metrics(usage: object) -> dict[str, int]:
    if not isinstance(usage, dict):
        return {}
    inputs, outputs = usage.get("input_tokens_details"), usage.get("output_tokens_details")
    values = {
        "input_tokens": usage.get("input_tokens"),
        "cached_tokens": inputs.get("cached_tokens") if isinstance(inputs, dict) else None,
        "output_tokens": usage.get("output_tokens"),
        "reasoning_tokens": outputs.get("reasoning_tokens") if isinstance(outputs, dict) else None,
        "total_tokens": usage.get("total_tokens"),
    }
    return {key: value for key, value in values.items() if type(value) is int and 0 <= value < 1e12}


def send_response(
    base_url: str,
    key: str,
    payload: dict,
    timeout: int | None,
    limit: int,
    *,
    diagnostics: dict | None = None,
    on_progress: Callable[[], None] | None = None,
) -> str:
    request = model_request(base_url, key, payload)
    started = monotonic()
    stats = diagnostics if diagnostics is not None else {}
    stats.update(
        phase="request_sent",
        stream=bool(payload.get("stream")),
        request_bytes=len(request.data),
        socket_timeout_seconds=timeout,
        response_limit_bytes=limit,
        max_output_tokens=payload.get("max_output_tokens"),
        received_bytes=0,
        output_characters=0,
        events={},
        heartbeats=0,
    )
    logger.info(
        "AI request started stream=%s request_bytes=%s socket_timeout_seconds=%s "
        "reused_text_count=%s saved_input_bytes=%s split_text_count=%s "
        "input_text_parts=%s max_input_text_characters=%s",
        bool(payload.get("stream")),
        len(request.data),
        timeout,
        stats.get("reused_text_count", 0),
        stats.get("saved_input_bytes", 0),
        stats.get("split_text_count", 0),
        stats.get("input_text_parts", 0),
        stats.get("max_input_text_characters", 0),
    )

    def notify():
        stats["elapsed_seconds"] = round(monotonic() - started, 3)
        if on_progress:
            on_progress()

    def failed(code):
        stats.update(outcome="failed", error_code=code)
        notify()

    notify()
    try:
        # No redirects or environment proxies: credentials go only to the approved endpoint.
        with open_model_response(request, timeout) as response:
            connected(response)
            stats.update(phase="connected", headers_seconds=round(monotonic() - started, 3))
            if type(getattr(response, "status", None)) is int:
                stats["http_status"] = response.status
            request_id = safe_identifier(response.headers.get("x-request-id"), key)
            if request_id:
                stats["request_id"] = request_id
            notify()
            if (
                payload.get("stream")
                and response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                == "text/event-stream"
            ):
                stats["response_format"] = "sse"
                result = read_stream(
                    response, limit, started, diagnostics=stats, on_progress=notify, secret=key
                )
            else:
                stats["response_format"] = "json"
                # Some compatible relays return one completed JSON response despite stream=true.
                body = response.read(limit + 1)
                stats["received_bytes"] = len(body)
                if len(body) > limit:
                    stats["termination"] = "response_size_limit"
                    raise AppError(502, "ai_invalid_response")
                result = json.loads(body)
    except HTTPError as exc:
        stats["http_status"] = exc.code
        stats["elapsed_seconds"] = round(monotonic() - started, 3)
        request_id = safe_identifier(exc.headers.get("x-request-id"), key)
        if request_id:
            stats["request_id"] = request_id
        try:
            body = exc.read(response_errors.MAX_ERROR_BYTES + 1)
            stats["error_body_truncated"] = len(body) > response_errors.MAX_ERROR_BYTES
            body = body[: response_errors.MAX_ERROR_BYTES]
            try:
                value = json.loads(body.decode("utf-8-sig"))
            except (ValueError, UnicodeError, RecursionError):
                value = {"error": {"message": body.decode("utf-8", errors="replace")}}
                stats.update(error_metadata(value), error_body_format="non_json")
            else:
                stats.update(error_metadata(value))
            stats["error_fingerprint"] = hashlib.sha256(body).hexdigest()
            response_errors.capture(body, stats, key)
        except (OSError, HTTPProtocolError):
            stats["error_body_format"] = "unavailable_or_non_json"
        code = response_error_code(exc.code, stats)
        safe = safe_snapshot(stats)
        logger.warning(
            "AI response upstream_status=%s elapsed_seconds=%.1f code=%s "
            "category=%s upstream_code=%s upstream_type=%s parameter=%s request_bytes=%s "
            "diagnostics=%s",
            exc.code,
            monotonic() - started,
            code,
            safe.get("error_category", "unknown"),
            safe.get("upstream_code", "-"),
            safe.get("upstream_type", "-"),
            safe.get("upstream_parameter", "-"),
            len(request.data),
            json.dumps(safe, ensure_ascii=True, sort_keys=True),
        )
        exc.close()
        failed(code)
        raise AppError(504 if exc.code == 504 else 502, code) from None
    except TimeoutError:
        stats.update(termination="network_timeout", network_error_type="TimeoutError")
        failed("ai_timeout")
        logger.warning("AI response network_timeout elapsed_seconds=%.1f", monotonic() - started)
        raise AppError(504, "ai_timeout") from None
    except URLError as exc:
        stats["network_error_type"] = type(exc.reason).__name__
        logger.warning("AI response connection_error elapsed_seconds=%.1f", monotonic() - started)
        code = "ai_timeout" if isinstance(exc.reason, TimeoutError) else "ai_connection_failed"
        failed(code)
        raise AppError(504 if code == "ai_timeout" else 502, code) from None
    except (ValueError, UnicodeError, OSError, HTTPProtocolError):
        stats.setdefault("termination", "invalid_response_or_connection")
        failed("ai_invalid_response")
        raise AppError(502, "ai_invalid_response") from None
    except AppError as exc:
        if stats.get("termination") in {"error", "response.failed", "response.incomplete"}:
            safe = safe_snapshot(stats)
            logger.warning(
                "AI response stream_error event=%s elapsed_seconds=%.1f code=%s "
                "category=%s upstream_code=%s upstream_type=%s parameter=%s "
                "request_id=%s response_id=%s request_bytes=%s received_bytes=%s "
                "output_characters=%s fingerprint=%s",
                safe.get("termination"),
                monotonic() - started,
                exc.detail,
                safe.get("error_category", "unknown"),
                safe.get("upstream_code", "-"),
                safe.get("upstream_type", "-"),
                safe.get("upstream_parameter", "-"),
                safe.get("request_id", "-"),
                safe.get("response_id", "-"),
                safe.get("request_bytes", 0),
                safe.get("received_bytes", 0),
                safe.get("output_characters", 0),
                safe.get("error_fingerprint", "-"),
            )
        failed(exc.detail)
        raise
    stats["phase"] = "validating_response"
    notify()
    try:
        output = output_text(result)
    except AppError as exc:
        stats.update(error_metadata(result))
        stats.update(outcome="failed", error_code=exc.detail)
        notify()
        raise
    usage = stats["usage"] = usage_metrics(result.get("usage"))
    stats["outcome"] = "completed"
    notify()
    logger.info(
        "AI response completed elapsed_seconds=%.1f received_bytes=%s output_characters=%s "
        "input_tokens=%s cached_tokens=%s output_tokens=%s reasoning_tokens=%s total_tokens=%s",
        stats.get("elapsed_seconds", 0),
        stats.get("received_bytes", 0),
        len(output),
        *(usage.get(name, "-") for name in USAGE_KEYS),
    )
    return output


def output_text(result: object) -> str:
    if not isinstance(result, dict) or result.get("status") != "completed":
        raise AppError(502, "ai_incomplete_response")
    output = result.get("output")
    if not isinstance(output, list) or not any(
        isinstance(item, dict)
        and isinstance(item.get("content"), list)
        and any(
            isinstance(part, dict)
            and part.get("type") == "output_text"
            and isinstance(part.get("text"), str)
            and part["text"].strip()
            for part in item["content"]
        )
        for item in output
    ):
        raise AppError(502, "ai_invalid_response")
    parts = [
        part
        for item in output
        if isinstance(item, dict) and isinstance(item.get("content"), list)
        for part in item["content"]
        if isinstance(part, dict)
    ]
    if any(part.get("type") == "refusal" for part in parts):
        raise AppError(502, "ai_refused")
    texts = [part.get("text") for part in parts if part.get("type") == "output_text"]
    if not all(isinstance(value, str) for value in texts):
        raise AppError(502, "ai_invalid_response")
    return "\n".join(texts)
