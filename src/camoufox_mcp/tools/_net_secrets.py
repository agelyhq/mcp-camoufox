"""Credentials that ride a captured request, and what is written down in their place.

``get_network_request`` renders one captured request as the browser saw it, and a
captured request is where the credentials of a signed-in profile live: the ``Cookie``
header of a profile whose login was established by hand IS that login, and a sign-in
POST body carries the very password that ``_secrets`` removes from ``args``.

Elided HERE, at the renderer, and not at the telemetry layer, for the same reason the
password value is elided in the snapshot walk: the tool result is handed to the model
AND written to the record as ``result``, which redaction never rewrites, and an agent
debugging a request has no more use for the cookie value than the log does. What it
needs is that the header was there, and how big it was.

Both elisions use the ``<redacted N chars>`` marker the rest of the product already
speaks, so a reader learns the shape of what was removed without learning its content.
"""

from __future__ import annotations

import re

from camoufox_mcp.tools._secrets import looks_secret, redact_value

# Header names whose VALUE is a credential on its own, matched case-insensitively: HTTP
# header names are case-insensitive, and Firefox hands most of them over lowercased.
#
# - ``cookie``: the session of a profile signed in by hand, which is the one asset this
#   product tells its users to build and keep. Replaying it IS being logged in.
# - ``set-cookie``: the same session travelling the other way; a rendered one is a
#   working login for whoever reads it.
# - ``authorization``: bearer tokens, Basic credentials (a base64 password), and every
#   signed API scheme.
# - ``proxy-authorization``: the same, addressed to the proxy rather than to the origin,
#   and this product ships a proxy option.
_SENSITIVE_HEADERS = frozenset({"cookie", "set-cookie", "authorization", "proxy-authorization"})

CONTENT_TYPE = "content-type"

_FORM_TYPE = "application/x-www-form-urlencoded"

# The longest field NAME either pattern will look at, and the one bound both share. It
# exists so an unclosed quote or a body with no separator cannot make the name group walk
# a megabyte from every position in the payload.
#
# It fails OPEN, deliberately: a name longer than this makes the whole pair unmatchable,
# so its value is rendered in clear rather than elided. That is the safe direction for a
# renderer whose job is to show the body — the alternative, an unbounded scan, is a
# pathological cost on the one tool that already handles the biggest strings in the
# product — and no field a form or an API actually posts is 200 characters long.
_MAX_FIELD_NAME = 200

# One ``name=value`` pair of a urlencoded body. Only the value is replaced, in place, so
# every other byte of the payload survives exactly as it was captured.
_FORM_FIELD = re.compile(rf"(?<![^&])([^=&]{{1,{_MAX_FIELD_NAME}}})=([^&]*)")

# One ``"name": "value"`` member of a JSON body, at any depth, with the value's own
# escapes. A member is recognised by the quote-colon shape, so a credential nested in a
# sub-object is caught by the same pass that catches a top-level one.
_JSON_FIELD = re.compile(rf'"([^"\\]{{1,{_MAX_FIELD_NAME}}})"(\s*:\s*)"((?:\\.|[^"\\])*)"')


def header_value(headers: dict[str, str], name: str) -> str:
    """One header, looked up the way HTTP defines names: without regard to case."""
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return ""


def redact_header(name: str, value: str) -> str:
    """A header's value, or its length when the value is itself the credential."""
    return redact_value(value) if name.strip().lower() in _SENSITIVE_HEADERS else value


def redact_post_data(body: str, content_type: str) -> str:
    """A request body with its credential-looking FIELDS elided, and nothing else touched.

    The least destructive option that stops a sign-in body being recorded in full.
    Dropping the body outright, or truncating it, would gut the tool: inspecting an API
    payload is what an agent calls ``get_network_request`` for, and the field that
    explains a 400 is as likely to be the last one as the first.

    So the unit of removal is one field, judged by its NAME against the same closed word
    list a typed value is judged by (``_secrets.SECRET_WORDS``) — one list, one place,
    one document — and the substitution is made in place: the bytes of a matched value
    are replaced, and every other byte of the payload is rendered exactly as captured.
    ``N`` counts the value as the BODY carries it, percent-encoded or backslash-escaped,
    because that is the shape actually removed.

    A body in a format this cannot parse with confidence is rendered verbatim rather than
    mangled by a guess: the dispatch is on the ``Content-Type``, and a type that is absent
    or unrecognised is left alone. Absent counts as unrecognised on purpose — a body sent
    with no declared type says nothing about how to read it, and guessing at one is the
    same mistake as guessing at an unknown one. What that leaves open is stated in
    ``docs/telemetry.md``.
    """
    kind = content_type.split(";", 1)[0].strip().lower()
    if kind == _FORM_TYPE:
        return _FORM_FIELD.sub(_redacted_pair, body)
    if kind.endswith("json"):
        return _JSON_FIELD.sub(_redacted_member, body)
    return body


def _redacted_pair(match: re.Match[str]) -> str:
    name, value = match.group(1), match.group(2)
    return f"{name}={redact_value(value)}" if _is_secret(name) else match.group(0)


def _redacted_member(match: re.Match[str]) -> str:
    name, separator, value = match.group(1), match.group(2), match.group(3)
    if not _is_secret(name):
        return match.group(0)
    # The marker holds no character JSON escapes, so it needs none: it is written as the
    # string literal it reads as.
    return f'"{name}"{separator}"{redact_value(value)}"'


def _is_secret(name: str) -> bool:
    """A field name that must not have its value written down.

    ``looks_secret`` is given no input type: a body field declares none, and the word
    list is the whole test here. It tokenizes on letters and digits, so a
    percent-encoded name reads as its own words (``mot%20de%20passe`` holds ``passe``).
    """
    return looks_secret("", (name,))
