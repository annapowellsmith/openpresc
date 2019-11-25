"""
Backport of the json_script template filter from Django 2.1
"""
import json

from django.core.serializers.json import DjangoJSONEncoder
from django.utils.html import format_html
from django.utils.safestring import mark_safe


_json_script_escapes = {ord(">"): "\\u003E", ord("<"): "\\u003C", ord("&"): "\\u0026"}


def json_script(value, element_id):
    """
    Escape all the HTML/XML special characters with their unicode escapes, so
    value is safe to be output anywhere except for inside a tag attribute. Wrap
    the escaped JSON in a script tag.
    """
    json_str = str(json.dumps(value, cls=DjangoJSONEncoder))
    json_str = json_str.translate(_json_script_escapes)
    return format_html(
        '<script id="{}" type="application/json">{}</script>',
        element_id,
        mark_safe(json_str),
    )
