"""Safe protocol metadata, never upstream prose or model/source content."""

import hashlib
import json
import re

ERROR_CODES = {
    "context_length_exceeded",
    "string_above_max_length",
    "string_too_long",
    "request_too_large",
    "max_output_tokens",
    "rate_limit_exceeded",
    "insufficient_quota",
    "invalid_api_key",
    "model_not_found",
    "invalid_request_error",
    "server_error",
    "timeout",
    "request_timeout",
    "upstream_timeout",
    "upstream_request_timeout",
    "connection_error",
    "overloaded_error",
    "content_filter",
    "content_policy_violation",
    "no_available_account",
}
PARAMETERS = {
    "model",
    "input",
    "messages",
    "instructions",
    "reasoning",
    "reasoning.effort",
    "max_output_tokens",
    "stream",
    "store",
    "temperature",
    "top_p",
    "tools",
    "tool_choice",
    "text",
    "text.format",
}
EVENTS = {
    "response.created",
    "response.in_progress",
    "response.output_item.added",
    "response.content_part.added",
    "response.output_text.delta",
    "response.output_text.done",
    "response.output_item.done",
    "response.content_part.done",
    "response.completed",
    "response.failed",
    "response.incomplete",
    "error",
    "response.refusal.delta",
    "response.refusal.done",
    "response.reasoning_summary_text.delta",
    "response.reasoning_summary_text.done",
    "response.reasoning_summary_part.added",
    "response.reasoning_summary_part.done",
}
USAGE_KEYS = ("input_tokens", "cached_tokens", "output_tokens", "reasoning_tokens", "total_tokens")
INPUT_ESTIMATE_KEYS = ("characters", "bytes", "approx_tokens", "images")


def safe_identifier(value, secret="") -> str | None:
    if not isinstance(value, str) or (secret and secret in value):
        return None
    if re.fullmatch(
        r"(?:[0-9a-fA-F]{8}-[0-9a-fA-F-]{27}|[0-9a-fA-F]{32}|(?:resp|req)_[A-Za-z0-9_-]{8,100})",
        value,
    ):
        return value
    return None


def _error_objects(value):
    # Read only error envelopes, never echoed input, source content or arbitrary fields.
    pending = [value]
    for _ in range(32):
        if not pending:
            break
        item = pending.pop(0)
        if isinstance(item, str):
            if item.lstrip().startswith(("{", "[", '"')):
                try:
                    decoded = json.loads(item)
                except (ValueError, RecursionError):
                    decoded = None
                if isinstance(decoded, dict | list | str) and decoded != item:
                    pending.append(decoded)
            yield {"message": item}
        elif isinstance(item, list):
            pending.extend(item[:32])
        elif isinstance(item, dict):
            yield item
            for key in ("response", "error", "detail", "details"):
                child = item.get(key)
                if isinstance(child, dict | str):
                    pending.append(child)
                elif isinstance(child, list):
                    pending.extend(child[:32])


def error_metadata(value: object) -> dict:
    """Classify transiently in memory; retain only known codes and a correlation hash."""
    if not isinstance(value, dict | list | str):
        return {"error_category": "unknown", "error_body_format": "non_json"}
    response = value.get("response") if isinstance(value, dict) else None
    response = response if isinstance(response, dict) else value if isinstance(value, dict) else {}
    errors = list(_error_objects(value))
    code = next(
        (e["code"] for e in errors if isinstance(e.get("code"), str) and e["code"] in ERROR_CODES),
        None,
    )
    kind = next(
        (e["type"] for e in errors if isinstance(e.get("type"), str) and e["type"] in ERROR_CODES),
        None,
    )
    message = " ".join(
        x[:16000]
        for error in errors
        for key in ("code", "type", "message", "msg")
        if isinstance(x := error.get(key), str)
    )
    text = message.lower()
    category = "unknown"
    for name, markers in (
        ("account_unavailable", ("no available account", "no_available_account")),
        (
            "context_limit",
            (
                "context_length",
                "context window",
                "maximum context",
                "too many tokens",
                "prompt is too long",
                "prompt too long",
                "input is too long",
                "input too long",
                "上下文超",
                "上下文长度",
            ),
        ),
        (
            "input_limit",
            (
                "string_above_max_length",
                "string_too_long",
                "string too long",
                "request_too_large",
                "request too large",
                "request body too large",
                "payload too large",
            ),
        ),
        ("output_limit", ("max_output_tokens", "maximum output", "output token limit")),
        ("timeout", ("timeout", "timed out", "deadline exceeded", "超时")),
        ("quota", ("insufficient_quota", "quota exceeded", "credit balance")),
        ("rate_limit", ("rate_limit", "rate limit", "too many requests")),
        ("authentication", ("invalid_api_key", "unauthorized", "authentication")),
        ("model_unavailable", ("model_not_found", "model not found")),
        ("overloaded", ("overloaded", "capacity", "unavailable")),
        ("connection", ("connection", "disconnect", "broken pipe")),
        ("parameters", ("unsupported", "not supported", "invalid parameter", "unknown parameter")),
    ):
        if any(marker in text for marker in markers):
            category = name
            break
    parameter = next(
        (
            e["param"]
            for e in errors
            if isinstance(e.get("param"), str) and e["param"] in PARAMETERS
        ),
        None,
    )
    if parameter is None:
        for error in errors:
            field = error.get("param")
            if isinstance(field, str):
                match = re.fullmatch(r"(input|messages)(?:\[\d+\]|\.[A-Za-z_]+|\.\d+)+", field)
                if match:
                    parameter = match[1]
                    break
    if parameter is None:
        parameter = next(
            (
                field
                for e in errors
                if isinstance(e.get("loc"), list)
                for field in e["loc"]
                if isinstance(field, str) and field in PARAMETERS
            ),
            None,
        )
    if isinstance(parameter, str) and parameter in PARAMETERS:
        if category == "unknown":
            category = "parameters"
    else:
        parameter = None
    details = response.get("incomplete_details")
    reason = details.get("reason") if isinstance(details, dict) else None
    result = {
        "error_category": category,
        "error_body_format": "json",
        "error_fingerprint": hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest(),
    }
    if parameter:
        result["upstream_parameter"] = parameter
    status = next(
        (
            status
            for e in errors
            if type(status := e.get("status_code", e.get("status"))) is int and 100 <= status <= 599
        ),
        None,
    )
    if type(status) is int and 100 <= status <= 599:
        result["upstream_http_status"] = status
    if category == "timeout" and isinstance(message, str):
        duration = re.search(
            r"\b(?:timed out after|timeout(?: of| after)?|deadline exceeded after)"
            r"\s+(\d+(?:\.\d+)?)\s*(milliseconds|ms|seconds|s)\b",
            message[:16000],
            re.IGNORECASE,
        )
        if duration:
            seconds = float(duration[1]) / (
                1000 if duration[2].lower() in ("ms", "milliseconds") else 1
            )
            if 0 < seconds <= 604800:
                result["reported_timeout_seconds"] = seconds
    for key, item in (
        ("upstream_code", code),
        ("upstream_type", kind),
        ("incomplete_reason", reason),
    ):
        if isinstance(item, str) and item in ERROR_CODES:
            result[key] = item
    return result


def safe_snapshot(stats: dict) -> dict:
    """Persist only controlled metadata; never arbitrary upstream text or payloads."""
    result = {}
    for group, keys in (("usage", USAGE_KEYS), ("input_estimate", INPUT_ESTIMATE_KEYS)):
        values = stats.get(group)
        if isinstance(values, dict):
            metrics = {
                key: value
                for key in keys
                if type(value := values.get(key)) is int and 0 <= value < 1e12
            }
            if metrics:
                result[group] = metrics
    if stats.get("call_mode") in ("RESPONSES_API", "CODEX_EXEC"):
        result["call_mode"] = stats["call_mode"]
    if stats.get("call_mode") == "CODEX_EXEC":
        version = stats.get("client_version")
        if isinstance(version, str) and re.fullmatch(r"[0-9][0-9A-Za-z.+-]{0,63}", version):
            result["client_version"] = version
        result["model_calls"] = None  # Process/turn count does not prove billed request count.
        if type(stats.get("exit_code")) is int:
            result["exit_code"] = stats["exit_code"]
        events = stats.get("cli_events", {})
        if isinstance(events, dict):
            result["cli_events"] = {
                k: v
                for k, v in events.items()
                if k
                in {
                    "thread.started",
                    "turn.started",
                    "turn.completed",
                    "turn.failed",
                    "item.started",
                    "item.updated",
                    "item.completed",
                    "error",
                }
                and type(v) is int
                and v >= 0
            }
    for key in ("error_body_truncated", "error_capture_failed"):
        if type(stats.get(key)) is bool:
            result[key] = stats[key]
    attempt_id = safe_identifier(stats.get("cli_attempt_id"))
    if attempt_id:
        result["cli_attempt_id"] = attempt_id
    terminal_id = safe_identifier(stats.get("cli_terminal_id"))
    if terminal_id:
        result["cli_terminal_id"] = terminal_id
    thread_id = safe_identifier(stats.get("cli_thread_id"))
    if thread_id:
        result["cli_thread_id"] = thread_id
    if stats.get("execution_policy") == "native-v1":
        result["execution_policy"] = "native-v1"
    error_ref = safe_identifier(stats.get("error_ref"))
    if error_ref:
        result["error_ref"] = error_ref
    if "socket_timeout_seconds" in stats and stats["socket_timeout_seconds"] is None:
        result["socket_timeout_seconds"] = None
    for key in (
        "elapsed_seconds",
        "received_bytes",
        "output_characters",
        "heartbeats",
        "http_status",
        "upstream_http_status",
        "reported_timeout_seconds",
        "first_byte_seconds",
        "headers_seconds",
        "last_activity_seconds",
        "request_bytes",
        "socket_timeout_seconds",
        "response_limit_bytes",
        "max_output_tokens",
        "reused_text_count",
        "saved_input_bytes",
        "split_text_count",
        "input_text_parts",
        "max_input_text_characters",
        "cli_event_count",
    ):
        value = stats.get(key)
        if type(value) in (int, float) and 0 <= value < 1e12:
            result[key] = value
    for key in ("request_id", "response_id"):
        value = safe_identifier(stats.get(key))
        if value:
            result[key] = value
    fingerprint = stats.get("error_fingerprint")
    if isinstance(fingerprint, str) and re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        result["error_fingerprint"] = fingerprint
    allowed = {
        "phase": {
            "connecting",
            "preparing",
            "request_sent",
            "connected",
            "receiving",
            "validating_response",
            "validating_report",
            "completed",
            "cli_starting",
            "cli_waiting",
            "cli_reasoning",
            "cli_reading",
            "cli_failed",
            "cli_native_running",
        },
        "error_category": {
            "unknown",
            "context_limit",
            "input_limit",
            "output_limit",
            "timeout",
            "quota",
            "rate_limit",
            "authentication",
            "model_unavailable",
            "account_unavailable",
            "overloaded",
            "connection",
            "parameters",
        },
        "termination": EVENTS
        | {
            "eof_without_completed",
            "response_size_limit",
            "done_without_completed",
            "response.refusal",
            "network_timeout",
            "invalid_response_or_connection",
        },
        "upstream_code": ERROR_CODES,
        "upstream_type": ERROR_CODES,
        "upstream_parameter": PARAMETERS,
        "incomplete_reason": ERROR_CODES,
        "outcome": {"completed", "failed"},
        "error_body_format": {"json", "non_json", "unavailable_or_non_json"},
    }
    for key, values in allowed.items():
        value = stats.get(key)
        if isinstance(value, str) and value in values:
            result[key] = value
    events = stats.get("events", {})
    if isinstance(events, dict):
        result["events"] = {
            k: v for k, v in events.items() if k in EVENTS and type(v) is int and 0 <= v < 1e12
        }
    return result
