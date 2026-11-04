from omnicore.desktop.model_card import safe_card_markdown


def test_html_model_card_is_readable_without_active_content():
    card = """---
license: mit
---
<h2>Overview</h2><p>Useful <strong>model</strong><br>text</p>
<script>do_bad()</script><img src="file:///etc/passwd">
```xml
<b>sample</b>
```
"""
    result = safe_card_markdown(card)
    assert "Overview" in result and "**model**" in result and "text" in result
    assert "<h2>" not in result and "<strong>" not in result
    assert "do_bad" not in result and "file:///etc/passwd" not in result
    assert "<b>sample</b>" in result and "license: mit" not in result
