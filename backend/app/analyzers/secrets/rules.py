"""Secret detection rules: known token signatures, secret-name semantics, placeholder suppression.

All rules are generic: they reason about names, values and data flow, never about specific file names, line
numbers or identifiers of any particular project.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass

from app.analyzers.secrets.entropy import char_classes, shannon_entropy

# --- signatures (layer 1) -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Signature:
    rule_id: str
    cls: str
    pattern: re.Pattern
    title: str
    group: int = 0


SIGNATURES: list[Signature] = [
    Signature("SEC-SIG-AWS", "aws-access-key", re.compile(r"\b((?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA)[A-Z0-9]{16})\b"),
              "AWS Access Key ID", 1),
    Signature("SEC-SIG-GITHUB", "github-token",
              re.compile(r"\b((?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"), "GitHub token", 1),
    Signature("SEC-SIG-TELEGRAM", "telegram-token", re.compile(r"\b(\d{8,10}:[A-Za-z0-9_-]{35})\b"), "Telegram Bot token", 1),
    Signature("SEC-SIG-SLACK", "slack-token", re.compile(r"\b(xox[abprs]-[A-Za-z0-9-]{10,})\b"), "Slack token", 1),
    Signature("SEC-SIG-STRIPE", "stripe-key", re.compile(r"\b((?:sk|rk)_live_[A-Za-z0-9]{16,})\b"), "Stripe live key", 1),
    Signature("SEC-SIG-GOOGLE", "google-api-key", re.compile(r"\b(AIza[0-9A-Za-z_\-]{35})\b"), "Google API key", 1),
    Signature("SEC-SIG-JWT", "jwt",
              re.compile(r"\b(eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})\b"), "JSON Web Token", 1),
    Signature("SEC-SIG-PEM", "private-key",
              re.compile(r"-----BEGIN ((?:RSA|EC|DSA|OPENSSH|PGP|ENCRYPTED) )?PRIVATE KEY( BLOCK)?-----"), "Private key block"),
    Signature("SEC-SIG-URLCRED", "url-credentials",
              re.compile(r"\b[a-z][a-z0-9+.\-]{1,20}://([^\s:/@'\"]{1,64}):([^\s@/'\"]{3,128})@[\w.\-]+"), "Credentials in URL", 2),
    Signature("SEC-SIG-JDBC", "db-credentials",
              re.compile(r"jdbc:[a-z0-9]+:[^\s'\"]*?[?&;](?:password|pwd)=([^&;\s'\"]{3,})", re.I), "JDBC URL with password", 1),
    Signature("SEC-SIG-BASIC", "basic-auth", re.compile(r"\bBasic\s+([A-Za-z0-9+/]{12,}={0,2})(?![A-Za-z0-9+/=])"),
              "Basic auth header", 1),
]

AWS_SECRET_NAME = re.compile(r"aws.?secret|secret.?access.?key", re.I)


def jwt_is_valid(token: str) -> bool:
    head = token.split(".", 1)[0]
    try:
        decoded = base64.urlsafe_b64decode(head + "=" * (-len(head) % 4))
        obj = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return False
    return isinstance(obj, dict) and "alg" in obj


def basic_is_valid(b64: str) -> bool:
    try:
        decoded = base64.b64decode(b64 + "=" * (-len(b64) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    return ":" in decoded and len(decoded.split(":", 1)[1]) >= 3


# --- names (layer 2) ------------------------------------------------------------------------------------------

def split_words(name: str) -> list[str]:
    """`legacyImportPassword` / `PRICING_API_KEY` / `x-api-key` / `pickup.callback.authorization` → words."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    return [w.lower() for w in re.split(r"[^A-Za-z0-9]+", s) if w]


PASSWORD_WORDS = {"password", "passwd", "pwd", "passphrase", "pass", "passw"}
APIKEY_PAIRS = {("api", "key"), ("app", "key"), ("access", "key"), ("subscription", "key"), ("client", "key"),
                ("license", "key"), ("service", "key")}
TOKEN_WORDS = {"token", "bearer", "authorization", "auth", "credential", "credentials", "secret", "apikey", "jwt",
               "signature", "signingkey", "privatekey"}
SECRET_PAIRS = {("client", "secret"), ("private", "key"), ("signing", "key"), ("secret", "key"), ("encryption", "key"),
                ("session", "key"), ("master", "key"), ("webhook", "secret"), ("access", "token")}
# words that make the name describe metadata about a secret rather than the secret itself
META_WORDS = {"variable", "var", "env", "name", "names", "field", "label", "hint", "prompt", "placeholder", "policy",
              "pattern", "regex", "length", "len", "min", "max", "header", "headers", "param", "parameter", "property",
              "prop", "path", "url", "uri", "endpoint", "file", "location", "type", "format", "encoder", "hasher",
              "hash", "hashed", "encoded", "expiry", "expires", "expiration", "ttl", "timeout", "count", "id", "ids",
              "enabled", "required", "validator", "validation", "reset", "change", "message", "error",
              "column", "attr", "attribute", "mode", "provider", "service", "client", "manager", "factory", "repository",
              "store", "storage", "cache", "filter", "converter", "scheme", "prefix", "suffix", "key_name", "keyname",
              "ref", "reference", "description", "title", "text", "template", "bean", "config", "configuration",
              "properties", "settings", "source", "parser", "generator", "class", "kind", "size"}


def name_semantics(name: str) -> str | None:
    """Return 'password' | 'api-key' | 'token' | None for an identifier/key name."""
    if not name:
        return None
    words = split_words(name)
    if not words:
        return None
    last = words[-1]
    if last in META_WORDS or (len(words) >= 2 and words[-1] in {"key"} and words[-2] in {"header", "property", "env"}):
        return None
    joined = "".join(words)
    pairs = set(zip(words, words[1:], strict=False))
    if any(w in PASSWORD_WORDS for w in words) or "password" in joined:
        return "password"
    if pairs & APIKEY_PAIRS or "apikey" in joined or "xapikey" in joined:
        return "api-key"
    if pairs & SECRET_PAIRS or any(w in TOKEN_WORDS for w in words) or joined.endswith(("token", "secret")):
        return "token"
    return None


# --- values ---------------------------------------------------------------------------------------------------

_PLACEHOLDER_WORDS = ("changeme", "change_me", "change-me", "example", "dummy", "sample", "placeholder", "replace_me",
                      "replaceme", "replace-me", "your_", "your-", "yourtoken", "yourkey", "yourpassword", "insert",
                      "todo", "fixme", "redacted", "masked", "secret_here", "token_here", "key_here", "password_here",
                      "notreal", "not-real", "fake", "test123", "<", ">", "…")
_TEMPLATE = re.compile(r"^\s*(\$\{[^}]*\}|#\{[^}]*\}|\{\{[^}]*\}\}|<[^>]*>|%[A-Za-z0-9_]+%|\$[A-Z_][A-Z0-9_]*)\s*$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
DOTTED_KEY = re.compile(r"^[a-z][a-z0-9]*(?:[.\-][a-z0-9]+)+$")
HEADER_NAME = re.compile(r"^(?:X-)?[A-Z][a-z]+(?:-[A-Z][A-Za-z]*)*$")
URL = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.I)
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
VERSION = re.compile(r"^v?\d+(\.\d+){1,3}([-.][A-Za-z0-9]+)?$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")


def is_placeholder(value: str | None) -> bool:
    if value is None:
        return True
    v = value.strip().strip("'\"")
    if not v or v.lower() in {"null", "none", "nil", "undefined", "empty", "true", "false", "secret", "password",
                              "token", "apikey", "api_key", "changeit", "admin", "root", "user", "guest", "test"}:
        return True
    if _TEMPLATE.match(v):
        return True
    low = v.lower()
    if any(w in low for w in _PLACEHOLDER_WORDS):
        return True
    if re.fullmatch(r"(.)\1{3,}", v) or re.fullmatch(r"[x*.\-_#]{3,}", low):
        return True
    if "xxx" in low or "***" in v or "..." in v:
        return True
    return False


# group:artifact:version with a numeric version or a property reference; used only by the entropy heuristic
MAVEN_COORDINATE = re.compile(r"^[a-z0-9_\-]+(\.[a-z0-9_\-]+)+:[A-Za-z0-9_.\-]+:"
                              r"(\d+(\.\d+)*([-.+][A-Za-z0-9.]+)?|\$\{?[A-Za-z0-9_.]+\}?)(:[A-Za-z0-9_.\-]+)?(@[a-z]+)?$")


def looks_like_secret(value: str, min_len: int = 6) -> bool:
    """Literal value plausibly being a real credential (not a name, key path, URL, sentence or placeholder)."""
    if value is None:
        return False
    v = value.strip()
    if len(v) < min_len or len(v) > 512:
        return False
    if is_placeholder(v):
        return False
    if any(c.isspace() for c in v):
        return False
    if ENV_NAME.match(v) or DOTTED_KEY.match(v) or HEADER_NAME.match(v) or VERSION.match(v):
        return False
    if URL.match(v) or v.startswith(("/", "./", "../", "classpath:", "file:")):
        return False
    if "%s" in v or "%d" in v or "{}" in v or "{0}" in v:
        return False
    if re.fullmatch(r"[a-z]+", v) and len(v) < 12:
        return False  # plain lowercase word
    if re.fullmatch(r"\d+", v) and len(v) < 12:
        return False
    return char_classes(v) >= 2 or shannon_entropy(v) >= 3.0


def strip_auth_scheme(value: str) -> tuple[str | None, str]:
    m = re.match(r"^\s*(Bearer|Token|Basic|Bot|ApiKey|Digest)\s+(\S+)\s*$", value, re.I)
    if m:
        return m.group(1), m.group(2)
    return None, value
