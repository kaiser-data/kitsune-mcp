"""_strip_html: visible text only (CodeQL py/bad-tag-filter)."""

from kitsune_mcp.utils import _strip_html


def test_script_and_style_are_dropped():
    html = "<p>keep</p><script>var x = 1;</script><style>p{color:red}</style><b>this</b>"
    assert _strip_html(html) == "keep this"


def test_end_tags_a_regex_misses():
    for end in ("</script >", "</SCRIPT>", "</script\n>"):
        html = f"<div>a</div><script>secret(){end}<div>b</div>"
        assert "secret" not in _strip_html(html), end
        assert "b" in _strip_html(html), end


def test_odd_end_tag_never_leaks_the_script():
    # Older html.parser releases don't end the script at `</script foo>` and
    # hide the rest of the page instead; newer ones end it. Neither leaks it.
    html = "<div>a</div><script>secret()</script foo><div>b</div>"
    assert "secret" not in _strip_html(html)


def test_entities_are_decoded():
    assert _strip_html("<p>a&nbsp;&amp;&#x27;b&eacute;</p>") == "a &'bé"


def test_unclosed_script_hides_the_rest():
    assert _strip_html("<p>x</p><script>never closed") == "x"
