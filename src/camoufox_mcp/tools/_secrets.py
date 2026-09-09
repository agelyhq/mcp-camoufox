"""Which typed values are secrets, and what is written down in their place.

573 fill values sat in the production logs in clear text before this module existed,
and there was no redaction anywhere in ``src/``. The hole gets worse the moment a
workflow reads those logs to generate a recipe: a password would be copied verbatim
into the file it writes.

Only the value goes. Its length, its target and the outcome of the call are the
substance of that recipe and stay, which is why the marker is a length-preserving
``<redacted N chars>``, the same elision the binary payloads already get.

Over-redaction is the failure mode to fear here, not under-redaction: a search term, a
filter or a date IS the recipe, and a log that hides them answers nothing. So the test
is deliberately narrow. It is the field's own declared type first, and failing that a
short closed list of words matched as WHOLE TOKENS, plus those tokens joined. ``code`` is
not on the list (a discount code is not a secret), and neither is ``key``/``clé`` (a
filter key is not either) — though "API Key" joins to ``apikey``, which is.

Each remaining word was re-read against a false positive someone actually hit, and kept
or dropped on that evidence:

- ``pin`` is gone. "PIN Code" is the Indian postal code and sits on any shipping form,
  "Code PIN produit" is a product filter, and a real PIN field is nearly always
  ``type="password"`` or named by another word on this list. It redacted more addresses
  than secrets.
- ``passe`` stays despite "Passe Navigo", because the joined-token fallback below only
  catches "Mot de passe" exactly: "Confirmez votre mot de passe" joins to a token that is
  on no list, and a missed password-confirmation field is worse than a missed transit
  pass.
- ``token`` and ``secret`` stay despite "Search by token name" and a "Secret Santa" list:
  both are the ordinary spelling of a credential that is permanent once leaked, and the
  loss on the other side is one search term on a niche page.
- ``cvv``, ``cvc``, ``otp``, ``totp``, ``apikey``, ``jeton`` and the password spellings
  stay: no plausible non-secret field is called any of them.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from camoufox_mcp.tools._target_notes import TargetNote

# The one signal the page itself declares, and the only reliable one.
_PASSWORD_TYPE = "password"

# Whole tokens, English and French, matched against 6 surfaces: EVERY name a field
# carries — its aria-label, its bound <label>, its placeholder and its form name, all of
# them, not just the one a reader sees — the selector that addressed it, and the NAME of
# each field of a captured request body, which ``_net_secrets`` judges by this same list.
# Short and explicit on purpose: every addition is a visible diff, and a visible chance to
# notice it would start hiding something a reader needs.
SECRET_WORDS = frozenset(
    {
        "password",
        "passwords",
        "passwd",
        "pwd",
        "passphrase",
        "passe",  # "mot de passe", "phrase de passe"
        "motdepasse",
        "secret",
        "secrets",
        "token",
        "jeton",
        "apikey",
        "otp",
        "totp",
        "cvv",
        "cvc",
    }
)

# The argument every value-carrying tool names its typed text with, at the top level for
# a single field and inside the ``{uid, value}`` objects of a multi-field call. Keyed on
# the shape of the arguments, never on which tool sent them: the wrapper that writes the
# record must not learn any tool's name.
_VALUE_KEY = "value"
_UID_KEY = "uid"

_TOKEN = re.compile(r"[a-z0-9]+")


def looks_secret(input_type: str, texts: Iterable[str | None]) -> bool:
    """Whether what resolved is a field a value must not be logged out of."""
    if input_type.strip().lower() == _PASSWORD_TYPE:
        return True
    return any(text and _has_secret_word(text) for text in texts)


def redact_value(value: str) -> str:
    """A value's shape without its content, like the ``<N bytes>`` binary elision."""
    return f"<redacted {len(value)} chars>"


def redact_args(args: dict[str, Any], notes: Sequence[TargetNote]) -> dict[str, Any]:
    """Write a typed value down only when the page confirmed a field it may be kept for.

    Runs BEFORE truncation, so a 12,000-char secret becomes the marker rather than a
    10,000-char prefix of itself.

    A value survives on 2 conditions, both read off what the call resolved: the element
    it was typed into was actually found, and nothing about that element looks secret.
    Neither condition alone is the rule.

    - Not found is not "not secret". ``fill(uid="e999", value=...)`` after a navigation
      invalidated every uid is the single most common retry an agent makes, and the value
      it re-typed is very often the password the previous call failed to enter. It never
      reached a page, so it is worth nothing to anything generated from this log, while a
      leaked credential is permanent. Same for a selector that matched nothing.
    - An address can be secret on its own: ``fill(selector="#password", ...)`` is redacted
      whether or not it ever matched, because the selector is a name too.

    What stays legible is the case the log exists for: a fill that landed, on a field
    nothing says is secret.
    """
    plain_uids = {note.uid for note in notes if note.uid and _is_plain(note)}
    all_plain = bool(notes) and all(_is_plain(note) for note in notes)
    return {key: _redacted(key, value, plain_uids, all_plain) for key, value in args.items()}


def _is_plain(note: TargetNote) -> bool:
    """A target a value may be written down for: one that resolved, and is not secret."""
    return note.resolved and not note.secret


def _redacted(key: str, value: Any, plain_uids: set[str], all_plain: bool) -> Any:
    """One argument, judged by the shape it arrives in.

    The 2 shapes are unrelated and each ignores what the other needs, so the choice is
    made once, here: the call's own typed text is judged against every target the call
    resolved, and anything nested is judged per ``{uid, value}`` object it contains.
    """
    if key == _VALUE_KEY and isinstance(value, str):
        return value if all_plain else redact_value(value)
    return _redacted_nested(value, plain_uids)


def _redacted_nested(value: Any, plain_uids: set[str]) -> Any:
    """Whatever a multi-field call wrapped its fields in, walked to reach them.

    The traversal deliberately mirrors ``telemetry._truncate_value``: a container one of
    them descends into and the other does not is a value that gets truncated and never
    redacted, which is the whole failure this module exists to prevent.
    """
    if isinstance(value, (list, tuple)):
        return [_redacted_nested(entry, plain_uids) for entry in value]
    if isinstance(value, dict):
        return _redacted_field(value, plain_uids)
    return value


def _redacted_field(entry: dict[str, Any], plain_uids: set[str]) -> dict[str, Any]:
    """One ``{uid, value}`` object of a multi-field call, judged by ITS own uid.

    Per uid rather than per call: a 6-field form with 1 password must still log the 5
    other values, which are what a recipe is made of. A uid no note vouches for is
    redacted for the same reason a single fill on a stale uid is.

    Anything that is not that object is walked rather than returned: a dict is where a
    future argument shape would nest its fields, and the traversal must reach them.
    """
    value = entry.get(_VALUE_KEY)
    if isinstance(value, str) and entry.get(_UID_KEY) not in plain_uids:
        return {**entry, _VALUE_KEY: redact_value(value)}
    return {key: _redacted_nested(item, plain_uids) for key, item in entry.items()}


def _has_secret_word(text: str) -> bool:
    """A whole-token match, plus the same tokens joined: "api key" is "apikey"."""
    tokens = _TOKEN.findall(_folded(text))
    if any(token in SECRET_WORDS for token in tokens):
        return True
    return "".join(tokens) in SECRET_WORDS


def _folded(text: str) -> str:
    """Case-folded and stripped of accents, so "Mot de Passe" reads as its tokens."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))
