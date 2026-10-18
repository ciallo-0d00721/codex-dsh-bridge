"""Bounded extraction of terminal turn failures from DSH event streams.

The extractor walks events in reverse (newest first), so the most recent
terminal failure wins. Only the whitelisted fields ``code`` and ``message``
are ever returned; arbitrary event fields are never echoed back.
"""

MAX_CODE_LENGTH = 80
MAX_MESSAGE_LENGTH = 2000
DEFAULT_CODE = "ERROR"
DEFAULT_MESSAGE = "Harness turn failed"
OUTPUT_TOKEN_LIMIT = "OUTPUT_TOKEN_LIMIT"
INCOMPLETE = "INCOMPLETE"

__all__ = [
    "MAX_CODE_LENGTH",
    "MAX_MESSAGE_LENGTH",
    "DEFAULT_CODE",
    "DEFAULT_MESSAGE",
    "OUTPUT_TOKEN_LIMIT",
    "INCOMPLETE",
    "extract_failure",
    "describe_incomplete",
]


def _bounded_code(value, redact):
    """Return a bounded code string, falling back to the safe default."""
    if isinstance(value, str) and value:
        return redact(value)[:MAX_CODE_LENGTH]
    return DEFAULT_CODE


def _bounded_message(value, redact):
    """Redact then bound a message; never emit the raw value."""
    if isinstance(value, str):
        raw = value
    else:
        raw = DEFAULT_MESSAGE
    redacted = redact(raw)
    if not isinstance(redacted, str):
        redacted = str(redacted)
    return redacted[:MAX_MESSAGE_LENGTH]


def extract_failure(events, redact):
    """Extract the newest terminal error from an event stream.

    ``events`` is expected to be a sequence of dictionaries shaped like
    ``{"type": "turn/end", "data": {"reason": {"kind": "error",
    "error": {"code": ..., "message": ...}}}}``.

    Returns ``{"code": <str, max 80 chars>,
    "message": redact(<str>)[:2000]}`` for the most recent terminal error,
    or ``None`` when no terminal error exists. Malformed event shapes are
    skipped silently; a terminal error with missing details yields the
    safe defaults ``ERROR`` / ``Harness turn failed``.

    ``redact`` is a required caller-supplied callback applied to both code
    and message strings; this function never logs or returns the raw input.
    """
    try:
        ordered = reversed(events)
    except TypeError:
        return None

    for event in ordered:
        if not isinstance(event, dict):
            continue
        if event.get("type") != "turn/end":
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        reason = data.get("reason")
        if not isinstance(reason, dict):
            continue
        if reason.get("kind") != "error":
            continue

        error = reason.get("error")
        if isinstance(error, dict):
            code = _bounded_code(error.get("code"), redact)
            message = _bounded_message(error.get("message"), redact)
        else:
            code = DEFAULT_CODE
            message = _bounded_message(None, redact)
        return {"code": code, "message": message}

    return None


_MAX_TOKENS_MESSAGE = (
    "Output stopped: the per-response generation limit was reached. "
    "Thinking and answer share that limit, so the reply was truncated "
    "and no retry was attempted. This is not an account-balance or "
    "quota error."
)


def _is_positive_int(value):
    """Return True only for positive ints, never for bools."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def describe_incomplete(reason, max_output_tokens=None):
    """Describe why a turn ended without a normal completion.

    ``reason`` is untrusted. For ``"max-tokens"`` the result uses the
    dedicated ``OUTPUT_TOKEN_LIMIT`` code and a fixed English message;
    the optional positive integer ``max_output_tokens`` is echoed into
    that message. Any other reason yields ``INCOMPLETE`` with
    ``"Harness stopped: <reason>"`` (``unknown`` for non-string input).
    The message is always bounded to ``MAX_MESSAGE_LENGTH`` characters.

    The caller is responsible for applying its own redaction before this
    result is published. No retry or limit increase is performed or
    suggested by this function.
    """
    if isinstance(reason, str) and reason == "max-tokens":
        message = _MAX_TOKENS_MESSAGE
        if _is_positive_int(max_output_tokens):
            message += " Configured output limit: {} tokens.".format(
                max_output_tokens
            )
        return {"code": OUTPUT_TOKEN_LIMIT, "message": message[:MAX_MESSAGE_LENGTH]}

    detail = reason if isinstance(reason, str) else "unknown"
    message = "Harness stopped: " + detail
    return {"code": INCOMPLETE, "message": message[:MAX_MESSAGE_LENGTH]}
