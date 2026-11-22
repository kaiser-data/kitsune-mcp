"""OAuth per RFC 8414 / RFC 9207 / OAuth 2.1 (decision 2026-11-22: follow best practice).

- The token endpoint may live on another host than the issuer (Google does).
- Every endpoint that receives a secret must use TLS (loopback excepted).
- The authorization response's `iss` must name the expected issuer (RFC 9207).
"""

import pytest

from kitsune_mcp import oauth


def _doc(**over):
    d = {
        "issuer": "https://accounts.example",
        "authorization_endpoint": "https://accounts.example/authorize",
        "token_endpoint": "https://oauth2.example-apis.com/token",  # another host: allowed
        "registration_endpoint": "https://accounts.example/register",
        "revocation_endpoint": "https://oauth2.example-apis.com/revoke",
        "code_challenge_methods_supported": ["S256"],
    }
    d.update(over)
    return d


def test_token_endpoint_on_another_host_is_accepted():
    meta = oauth._meta_from(_doc())
    assert meta is not None and meta.token_endpoint == "https://oauth2.example-apis.com/token"


@pytest.mark.parametrize("field", ["registration_endpoint", "revocation_endpoint"])
def test_plaintext_secret_endpoints_are_dropped(field):
    meta = oauth._meta_from(_doc(**{field: "http://accounts.example/x"}))
    assert meta is not None and getattr(meta, field) is None


def test_loopback_endpoints_stay_allowed():
    meta = oauth._meta_from(_doc(revocation_endpoint="http://127.0.0.1:9000/revoke"))
    assert meta.revocation_endpoint == "http://127.0.0.1:9000/revoke"


def test_iss_support_flag_is_read():
    assert oauth._meta_from(_doc(authorization_response_iss_parameter_supported=True)).iss_required
    assert not oauth._meta_from(_doc()).iss_required


def _cb(**kw):
    cb = oauth._CallbackState()
    cb.state, cb.code = "S", "CODE"
    for k, v in kw.items():
        setattr(cb, k, v)
    return cb


def test_callback_with_matching_iss_passes():
    meta = oauth._meta_from(_doc())
    assert oauth._check_callback(_cb(iss="https://accounts.example"), "S", meta) == "CODE"


def test_callback_with_another_issuer_is_refused():
    meta = oauth._meta_from(_doc())
    with pytest.raises(RuntimeError, match="issuer"):
        oauth._check_callback(_cb(iss="https://evil.example"), "S", meta)


def test_error_callback_from_another_issuer_names_the_mixup():
    meta = oauth._meta_from(_doc())
    with pytest.raises(RuntimeError, match="issuer"):
        oauth._check_callback(_cb(iss="https://evil.example", error="denied"), "S", meta)


def test_missing_iss_refused_when_server_promises_it():
    meta = oauth._meta_from(_doc(authorization_response_iss_parameter_supported=True))
    with pytest.raises(RuntimeError, match="iss"):
        oauth._check_callback(_cb(), "S", meta)


def test_missing_iss_allowed_when_not_promised():
    assert oauth._check_callback(_cb(), "S", oauth._meta_from(_doc())) == "CODE"


def test_state_mismatch_still_refused():
    with pytest.raises(RuntimeError, match="state"):
        oauth._check_callback(_cb(state="other"), "S", oauth._meta_from(_doc()))


def test_handler_records_iss():
    cb = oauth._CallbackState()
    oauth._record_callback(cb, "code=C&state=S&iss=https%3A%2F%2Faccounts.example")
    assert (cb.code, cb.state, cb.iss) == ("C", "S", "https://accounts.example")
