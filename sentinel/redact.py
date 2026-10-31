"""Redact secret-looking values before anything leaves the runner for an LLM.

Two layers:
1. Key based: values under keys such as Password, Token or ApiKey.
2. Pattern based: known credential formats anywhere in a string.

The same scan feeds the risk engine, so a hardcoded secret in a template is
both hidden from the model and reported as a finding.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_KEY = re.compile(
    r"(password|passwd|passphrase|secret|token|api[_-]?key|private[_-]?key|credential)",
    re.IGNORECASE,
)
# Keys that mention a secret but hold a reference to it, not the secret itself.
_REFERENCE_SUFFIXES = ("arn", "id", "name", "ids", "names", "policy", "type", "rotation")
_SAFE_VALUE_PREFIXES = ("{{resolve:", "arn:aws", "arn:aws-us-gov", "${")

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_\w{22,255})\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "private-key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    ),
    ("jwt", re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}\b")),
)
_CONNECTION_STRING = re.compile(
    r"(?P<scheme>(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqps?)://[^:\s/@]+:)"
    r"(?P<password>[^@\s]+)(?P<at>@)",
    re.IGNORECASE,
)


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    if not _SENSITIVE_KEY.search(lowered):
        return False
    return not lowered.endswith(_REFERENCE_SUFFIXES)


@dataclass
class Redactor:
    """Walks JSON-like data, replaces secrets, and remembers where it found them."""

    min_secret_length: int = 6
    hits: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.hits)

    def value(self, key: str, value: Any, path: str = "") -> Any:
        """Redact a single value that lives under `key`."""
        location = f"{path}.{key}" if path else key
        if isinstance(value, str) and is_sensitive_key(key) and self._looks_secret(value):
            self.hits.append(f"{location} (sensitive key)")
            return REDACTED
        return self.walk(value, location)

    def walk(self, data: Any, path: str = "") -> Any:
        if isinstance(data, dict):
            return {k: self.value(str(k), v, path) for k, v in data.items()}
        if isinstance(data, list):
            return [self.walk(v, f"{path}[{i}]") for i, v in enumerate(data)]
        if isinstance(data, str):
            return self._string(data, path)
        return data

    def _looks_secret(self, value: str) -> bool:
        stripped = value.strip()
        if len(stripped) < self.min_secret_length or stripped == REDACTED:
            return False
        if stripped.startswith(_SAFE_VALUE_PREFIXES):
            return False
        return stripped.lower() not in {"true", "false", "none", "null", "****"}

    def _string(self, text: str, path: str) -> str:
        stripped = text.strip()
        if stripped[:1] in "{[" and len(stripped) > 1:
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict | list):
                return json.dumps(self.walk(parsed, path), sort_keys=True)

        result = text
        for label, pattern in _PATTERNS:
            result, n = pattern.subn(REDACTED, result)
            self.hits.extend([f"{path or 'value'} ({label})"] * n)
        result, n = _CONNECTION_STRING.subn(rf"\g<scheme>{REDACTED}\g<at>", result)
        self.hits.extend([f"{path or 'value'} (connection-string password)"] * n)
        return result


def redact(data: Any) -> tuple[Any, int]:
    """Convenience wrapper: returns the redacted copy and the number of redactions."""
    redactor = Redactor()
    return redactor.walk(data), redactor.count
