from auth import (hash_password, verify_password,
                  make_session_token, parse_session_token)
from auth import LoginThrottle


def test_hash_verify_roundtrip():
    enc = hash_password("correct horse")
    assert verify_password("correct horse", enc) is True
    assert verify_password("wrong", enc) is False


def test_verify_rejects_empty_or_malformed():
    assert verify_password("x", "") is False
    assert verify_password("x", "not-a-hash") is False
    assert verify_password("x", "bcrypt$1$2$3$4$5") is False
    assert verify_password("x", "scrypt$16384$8$1$zz$zz") is False


def test_token_roundtrip():
    tok = make_session_token("s3cr3t", 1, now=1000)
    assert parse_session_token(tok, "s3cr3t", 1, now=1000) is True


def test_token_rejects_tampering_and_wrong_secret():
    tok = make_session_token("s3cr3t", 1, now=1000)
    assert parse_session_token(tok + "x", "s3cr3t", 1, now=1000) is False
    assert parse_session_token(tok, "other", 1, now=1000) is False
    assert parse_session_token("no-dot", "s3cr3t", 1, now=1000) is False


def test_token_rejects_wrong_cred_version():
    tok = make_session_token("s3cr3t", 1, now=1000)
    assert parse_session_token(tok, "s3cr3t", 2, now=1000) is False


def test_token_expiry_and_clock_skew():
    tok = make_session_token("s3cr3t", 1, now=1000)
    assert parse_session_token(tok, "s3cr3t", 1, now=1000 + 29 * 86400) is True
    assert parse_session_token(tok, "s3cr3t", 1, now=1000 + 31 * 86400) is False
    assert parse_session_token(tok, "s3cr3t", 1, now=500) is False  # "issued in the future"


def test_verify_rejects_oversized_scrypt_params():
    assert verify_password("x", "scrypt$999999999999999999999999$8$1$abab$cdcd") is False


def test_token_rejects_non_ascii_segments():
    assert parse_session_token("payload.ÿÿ", "s3cr3t", 1) is False
    assert parse_session_token("ÿÿ.sig", "s3cr3t", 1) is False


def test_throttle_allows_the_free_attempts_then_blocks():
    tr = LoginThrottle()
    for _ in range(LoginThrottle.FREE_ATTEMPTS):
        assert tr.retry_after("10.0.0.1", now=0) == 0
        tr.record_failure("10.0.0.1", now=0)
    assert tr.retry_after("10.0.0.1", now=0) > 0


def test_throttle_first_cooldown_is_the_first_tier():
    tr = LoginThrottle()
    for _ in range(LoginThrottle.FREE_ATTEMPTS):
        tr.record_failure("10.0.0.1", now=0)
    assert tr.retry_after("10.0.0.1", now=0) == LoginThrottle.COOLDOWNS[0]


def test_throttle_cooldown_is_monotonic_across_the_boundary():
    tr = LoginThrottle()
    seen = []
    for _ in range(LoginThrottle.FREE_ATTEMPTS + 5):
        tr.record_failure("10.0.0.1", now=0)
        seen.append(tr.retry_after("10.0.0.1", now=0))
    assert seen == sorted(seen)
    assert seen[-1] == LoginThrottle.COOLDOWNS[-1]


def test_throttle_success_clears_the_ip():
    tr = LoginThrottle()
    for _ in range(6):
        tr.record_failure("10.0.0.1", now=0)
    assert tr.retry_after("10.0.0.1", now=1) > 0
    tr.record_success("10.0.0.1")
    assert tr.retry_after("10.0.0.1", now=1) == 0


def test_throttle_forgets_old_failures():
    tr = LoginThrottle()
    for _ in range(6):
        tr.record_failure("10.0.0.1", now=0)
    assert tr.retry_after("10.0.0.1", now=LoginThrottle.WINDOW + 1) == 0


def test_throttle_is_per_ip():
    tr = LoginThrottle()
    for _ in range(6):
        tr.record_failure("10.0.0.1", now=0)
    assert tr.retry_after("10.0.0.2", now=0) == 0
