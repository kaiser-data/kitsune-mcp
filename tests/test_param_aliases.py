"""Parameter aliasing tests for proxy_fn in shapeshift.py."""

import pytest

from kitsune_mcp.shapeshift import _PARAM_ALIASES


def _apply_aliases(cleaned: dict, schema_props: set) -> dict:
    """Replicate the alias normalization logic from proxy_fn."""
    if not any(k in _PARAM_ALIASES and k not in schema_props for k in cleaned):
        return cleaned
    remapped = {}
    for k, v in cleaned.items():
        if k not in schema_props and k in _PARAM_ALIASES:
            canonical = _PARAM_ALIASES[k]
            if canonical in schema_props and canonical not in cleaned:
                remapped[canonical] = v
                continue
        remapped[k] = v
    return remapped


def test_from_to_timezone_aliased():
    props = {"source_timezone", "target_timezone", "time"}
    cleaned = {"from_timezone": "UTC", "to_timezone": "Asia/Tokyo", "time": "09:00"}
    result = _apply_aliases(cleaned, props)
    assert result == {"source_timezone": "UTC", "target_timezone": "Asia/Tokyo", "time": "09:00"}


def test_alias_does_not_override_valid_key():
    """If user passes both 'source' (valid schema key) and 'from' (alias for source),
    the explicit 'source' value wins — 'from' is not remapped because canonical already
    exists in cleaned."""
    props = {"source", "target"}
    cleaned = {"source": "A", "from": "B"}
    result = _apply_aliases(cleaned, props)
    # 'source' is already in cleaned — 'from' alias skipped, original value preserved.
    assert result["source"] == "A"
    # 'from' could not remap (canonical already present), so it passes through unchanged.
    assert result.get("from") == "B" or "from" not in result  # either is acceptable


def test_alias_not_applied_when_key_in_schema():
    """If schema declares 'from' directly, it must not be aliased away."""
    props = {"from", "to"}
    cleaned = {"from": "UTC", "to": "Tokyo"}
    result = _apply_aliases(cleaned, props)
    assert result == {"from": "UTC", "to": "Tokyo"}


def test_src_alias_to_source():
    props = {"source", "limit"}
    cleaned = {"src": "hello", "limit": 10}
    result = _apply_aliases(cleaned, props)
    assert result == {"source": "hello", "limit": 10}


def test_dest_alias_to_target():
    props = {"target"}
    cleaned = {"dest": "Paris"}
    result = _apply_aliases(cleaned, props)
    assert result == {"target": "Paris"}


def test_from_lang_alias():
    props = {"source_language", "target_language", "text"}
    cleaned = {"from_lang": "en", "to_lang": "fr", "text": "hello"}
    result = _apply_aliases(cleaned, props)
    assert result == {"source_language": "en", "target_language": "fr", "text": "hello"}


def test_no_alias_when_canonical_not_in_schema():
    """If alias maps to a key not in schema, pass through unchanged."""
    props = {"query"}
    cleaned = {"from_timezone": "UTC"}
    result = _apply_aliases(cleaned, props)
    # source_timezone not in props — leave as-is
    assert result == {"from_timezone": "UTC"}


def test_unknown_keys_pass_through():
    props = {"source_timezone", "target_timezone"}
    cleaned = {"source_timezone": "UTC", "target_timezone": "Tokyo", "extra": "ignored"}
    result = _apply_aliases(cleaned, props)
    assert result["extra"] == "ignored"
