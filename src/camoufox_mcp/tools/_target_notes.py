"""What a call resolved, carried from the tool body to the record it earns.

A telemetry line reading ``uid=e6600005`` names nothing outside the document that
minted it, so a log read a week later cannot say WHAT was clicked, and a recipe
generated from it cannot either. An element's identity is known at resolution time and
nowhere else; this module is the channel from there to the record.

The channel is a context variable rather than a parameter because the ``@tool`` wrapper
cannot see anything a body computed: it calls the handler with the arguments the agent
sent and reads the value it returns. One scratch list per call, opened by the wrapper
and closed with it, so nothing one call resolved can reach the next — including under
the daemon, where several profiles share a process and every request is its own task.

The tools that act on an element declare :func:`target_analytics` at registration, which
is what keeps the wrapper free of any knowledge of which tools those are.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from camoufox_mcp.telemetry import truncate_arg
from camoufox_mcp.tools._secrets import looks_secret

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from camoufox_mcp.dom import Hit

_TARGETS: ContextVar[list[TargetNote] | None] = ContextVar("camoufox_call_targets", default=None)


@dataclass(frozen=True)
class TargetNote:
    """One element a call addressed, and what the page said about it.

    ``resolved`` tells an address apart from an element: a call whose selector never
    matched still records what it was looking for, and must not claim it found it.
    """

    uid: str | None = None
    selector: str | None = None
    tag: str = ""
    role: str = ""
    input_type: str = ""
    label: str = ""
    name_sources: str = ""
    text: str = ""
    resolved: bool = False

    @property
    def secret(self) -> bool:
        """Whether a value typed into this element must not be written down.

        Read from ``name_sources``, every name the page gives the element, and not from
        the one that won the race to be its ``label``: with
        ``<label for=cvc>Security code</label>``, the label answers and the form name
        that says ``cvc`` never gets asked.

        The element's own text is deliberately not consulted: a "Forgot your password?"
        link is not a secret field, and a field IS named by what it is called, not by
        what it currently contains.
        """
        return looks_secret(self.input_type, (self.name_sources, self.selector))

    def fields(self) -> dict[str, Any]:
        """The record's view of this target: what is known, and nothing that is empty.

        ``resolved`` is written out rather than left to be inferred from the presence of
        ``tag``: it is the one thing this note exists to state, and a reader should not
        have to know which fields only the page can write in order to learn whether the
        call found anything.

        ``name_sources`` is not among them: it is the secret test's input, and a label
        reading "Security code cvc" is worse to read than one reading "Security code".

        EVERY string here is capped, in this one place, at the argument ceiling. This
        dict is flattened onto the JSON line without passing through the argument
        truncation, and all of it but the uid is written by the page or by the caller:
        a 200 KB selector was recorded in full beside the 10,000 characters of it that
        ``args`` kept, and ``tag`` (a custom element's name) has no length limit of its
        own either. ``role``, ``label`` and ``text`` arrive already capped at 80 by the
        walk, so the ceiling never fires on them; capping them alike costs nothing and
        keeps the rule readable as one sentence.
        """
        known = {
            "uid": self.uid,
            "selector": self.selector,
            "tag": self.tag,
            "role": self.role,
            "input_type": self.input_type,
            "label": self.label,
            # A secret field's own text can be the secret (a contenteditable holds what
            # was typed into it), so it goes with the value it belongs to.
            "text": "" if self.secret else self.text,
        }
        out = {key: truncate_arg(value) for key, value in known.items() if value}
        out["resolved"] = self.resolved
        if self.secret:
            out["secret"] = True
        return out


@contextmanager
def call_targets() -> Iterator[None]:
    """One call's scratch list, opened around a tool call and discarded with it."""
    token = _TARGETS.set([])
    try:
        yield
    finally:
        _TARGETS.reset(token)


def note_target(uid: str | None = None, selector: str | None = None) -> None:
    """Record the address a call is about to act on, before anything is done with it.

    Noted first so a failure still says what was attempted: an element that never
    resolved is exactly the case a log is read for.
    """
    notes = _TARGETS.get()
    if notes is not None:
        notes.append(TargetNote(uid=uid, selector=selector))


def note_identity(uid: str, hit: Hit) -> None:
    """Attach what the page reported about the element behind ``uid``.

    Enriches the address already noted for it — a selector's note is waiting with no uid
    yet — or stands on its own for a caller that addresses a uid directly.
    """
    notes = _TARGETS.get()
    if notes is None:
        return
    identity = {
        "tag": hit.tag,
        "role": hit.role,
        "input_type": hit.input_type,
        "label": hit.label,
        "name_sources": hit.name_sources,
        "text": hit.text,
    }
    for index in reversed(range(len(notes))):
        note = notes[index]
        if not note.resolved and note.uid in (uid, None):
            notes[index] = replace(note, uid=uid, resolved=True, **identity)
            return
    notes.append(TargetNote(uid=uid, resolved=True, **identity))


def note_when(uid: str) -> Callable[[Hit], None]:
    """A one-argument sink for a layer that measures an element without owning it.

    ``dom/`` hands the hit to whoever asked for it and learns nothing about telemetry;
    the tool binds the uid it already knows. It is the same note either way.
    """
    return lambda hit: note_identity(uid, hit)


def noted_targets() -> list[TargetNote]:
    """Every target this call resolved, in the order it resolved them."""
    notes = _TARGETS.get()
    return list(notes) if notes else []


def target_analytics(_args: dict[str, Any]) -> dict[str, Any]:
    """The telemetry enrichment of a tool that acts on a resolved element.

    Total by construction: it reads a list this module owns and never the call's
    arguments. That is what it owes the wrapper, which runs it inside the ``finally``
    that writes the record; the wrapper does not take it on trust.

    One key, ``targets``, chosen not to collide with any field of ``UsageRecord``: the
    dict is flattened onto the same JSON line, so a name already in use there would
    silently replace it.
    """
    notes = noted_targets()
    return {"targets": [note.fields() for note in notes]} if notes else {}
