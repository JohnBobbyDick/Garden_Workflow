import base64
import os

import pytest

from app.core.crypto import CryptoError, SecretBox
from app.core.masking import Masker, mask_tail


def _key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


def test_secretbox_roundtrip_and_versioned_ciphertext():
    box = SecretBox({1: _key()}, current=1)
    token = box.encrypt("s3cr3t-value")
    assert token.startswith("v1:")
    assert "s3cr3t-value" not in token
    assert box.decrypt(token) == "s3cr3t-value"


def test_secretbox_old_key_version_still_decrypts_after_rotation():
    k1, k2 = _key(), _key()
    old = SecretBox({1: k1}, current=1).encrypt("abc")
    rotated = SecretBox({1: k1, 2: k2}, current=2)
    assert rotated.decrypt(old) == "abc"
    assert rotated.encrypt("abc").startswith("v2:")


def test_secretbox_tampered_ciphertext_fails_loudly():
    box = SecretBox({1: _key()}, current=1)
    token = box.encrypt("abc")
    bad = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(CryptoError):
        box.decrypt(bad)


def test_secretbox_rejects_short_key():
    with pytest.raises(CryptoError):
        SecretBox({1: base64.b64encode(b"short").decode()}, current=1)


def test_mask_tail_shows_only_last_chars():
    assert mask_tail("1234567890abcd") == "••••abcd"
    assert mask_tail("abc") == "••••"


def test_masker_replaces_registered_values_and_patterns():
    m = Masker()
    m.register("hunter2-very-secret")
    text = "login failed for hunter2-very-secret; token ghp_" + "a" * 36
    out = m.mask(text)
    assert "hunter2-very-secret" not in out
    assert "ghp_" + "a" * 36 not in out
    assert "login failed" in out


def test_masker_ignores_too_short_values():
    m = Masker()
    m.register("ab")
    assert m.mask("ab cab") == "ab cab"


def test_masker_masks_nested_structures():
    m = Masker()
    m.register("topsecretvalue")
    data = {"a": ["x topsecretvalue y", {"b": "topsecretvalue"}], "n": 3}
    out = m.mask_obj(data)
    assert "topsecretvalue" not in repr(out)
    assert out["n"] == 3


def test_masker_masks_url_credentials_and_bearer():
    m = Masker()
    out = m.mask("GET https://user:pa55word@host/x Authorization: Bearer abcdefghijklmnop123")
    assert "pa55word" not in out
    assert "abcdefghijklmnop123" not in out


def test_log_filter_keeps_args_structure_and_masks_values():
    import logging

    from app.core.masking import MaskingLogFilter, global_masker
    global_masker.register("logfilter-secret-123")
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                            ("127.0.0.1:1", "GET", "/x?token=logfilter-secret-123", "1.1", 200), None)
    assert MaskingLogFilter().filter(rec) is True
    assert isinstance(rec.args, tuple) and len(rec.args) == 5  # uvicorn's formatter unpacks 5 args
    assert "logfilter-secret-123" not in rec.getMessage()
