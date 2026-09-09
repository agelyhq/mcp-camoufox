// What a resolved element IS, as opposed to what a tree line calls it.
//
// Split from the naming rules above because it answers a different question and has a
// different consumer: those compute the name a rendered line prints, these compute the
// identity that travels back with one measured element, so a record written now can say
// what was acted on long after the uid that named it stopped meaning anything.

// How far into one page-controlled name the secret test still looks. Wide enough for a
// sentence-length label to keep its decisive word (a real one measured at offset 85),
// narrow enough that 4 names cannot grow a payload rebuilt on every poll iteration.
const SECRET_SCAN_CAP = 240;

// How much of an element's own text is read before `ownText` caps it for the record. It
// does NOT bound the read: `el.textContent` materialises the whole subtree string first,
// and nothing short of a walk would avoid that. What it bounds is what happens to that
// string afterwards — the collapse regex over it, and the copy that crosses the protocol
// — on every poll iteration of a mistargeted action on a large container.
//
// It lives here and not with the rendering caps in 20_names.js because no renderer reads
// it: `ownText`, 20 lines down, is its only consumer. It shares the value 240 with
// SECRET_SCAN_CAP and means something else — that one is how far from the start of a
// NAME a secret word may sit and still be found, this one is how much of an element's
// TEXT is worth carrying back — so they are 2 constants rather than 1 reused twice, and
// either can move without dragging the other.
const TEXT_SCAN_CAP = 240;

// What the element is CALLED, from the 4 places that answer without descending INTO it:
// aria-label, the <label> bound to it, its placeholder, then its form name. All 4 come
// back, in that order, because 2 different questions are asked of them and only 1 wants
// a single answer.
//
// A first-wins chain answered both, and it hid one whole shape: with
// `<label for=cvc>Security code</label><input type=text name=cvc>`, the bound label wins
// and the form name — the only part of that field that says "card verification code" —
// was never looked at. An OTP field named `otp` behind `aria-label="Digit 1"` is the same
// shape, and so is a password field whose "show password" toggle flipped its type.
//
// The one walk this can do is over a bound <label>, and `el.labels` is empty for
// everything that has none, which is most of what gets resolved.
function namesOf(el) {
  const out = [];
  out[out.length] = collapse(el.getAttribute('aria-label'));
  out[out.length] = labelText(el);
  out[out.length] = collapse(el.placeholder);
  // `HTMLFormElement` is [LegacyOverrideBuiltIns], so a form holding a control named
  // `name` answers with that CONTROL rather than with a string, and collapsing it would
  // stringify an element into this field. Every other element answers a DOMString or
  // nothing at all.
  out[out.length] = typeof el.name === 'string' ? collapse(el.name) : '';
  return out;
}

// THE name, for a reader: the first source that answered.
function firstName(names) {
  for (let i = 0; i < names.length; i++) {
    if (names[i]) return capped(names[i], NAME_CAP);
  }
  return '';
}

// EVERY name, for the test that decides whether a typed value may be written down. It is
// deliberately not what gets recorded as the label: a record naming a field
// "Security code cvc" reads worse than one naming it "Security code", and the reader of a
// log wants the name a human would use.
//
// Capped far looser than `firstName`, not uncapped: `NAME_CAP` exists so a rendered line
// stays readable and nothing rendered reads this, but a page controls all 4 of these
// strings and this payload is rebuilt on every poll iteration, so leaving them unbounded
// hands the page the same lever `role` was just capped to take away. Truncating at 80
// threw the decisive word away — the label "Pour valider la création de votre compte,
// veuillez confirmer ci-dessous votre mot de passe" says "passe" at offset 85 — and the
// field then had its typed value written to the log in clear. `SECRET_SCAN_CAP` is the
// distance a secret word can sit from the start of a name and still be found; past it a
// name is prose, not a label.
//
// Concatenated in the loop rather than joined: `Array.prototype.join` resolves on the
// page's own prototype at call time, so a page that replaces it decides what this
// returns, and this string is the SOLE input of the secret test.
function allNames(names) {
  let out = '';
  for (let i = 0; i < names.length; i++) {
    if (names[i]) out += (out ? ' ' : '') + capped(names[i], SECRET_SCAN_CAP);
  }
  return out;
}

// What the element SAYS, read off the node rather than collected from it: `textContent`
// is one native read where `contentText` is a recursive walk. A container whose contents
// are data or a whole section of the page says nothing of its own, and an input carries
// its text in `value` only when that value IS its visible label.
function ownText(el) {
  if (el.tagName === 'INPUT') return capped(elementText(el), NAME_CAP);
  if (isDataContent(el)) return '';
  const raw = el.textContent;
  return capped(collapse(raw ? raw.slice(0, TEXT_SCAN_CAP) : ''), NAME_CAP);
}

// The identity a resolved element carries back to the record that names what a call
// acted on. `uid=e6600005` means nothing in any later document; role, type, label and
// text do.
//
// The full accessible-name computation is NOT run here: `resolve` is re-probed until the
// element settles, so its subtree collection would be paid per poll iteration, on every
// click, every fill and every element screenshot. What is left is property reads, a
// sliced `textContent`, and the bound-label walk `namesOf` names.
//
// The keys are the Python `Hit` field names verbatim, which is what `_hit_from` requires.
//
// `role` is capped like the other names for the reason none of them is trusted: it is a
// raw author attribute, read straight off the element, and a 65,000-character one used to
// cross the protocol whole on every poll iteration of every action. The Python side caps
// it too, but only once it has already been paid for.
function identityOf(el) {
  const names = namesOf(el);
  return {
    role: capped(roleOf(el), NAME_CAP),
    input_type: el.tagName === 'INPUT' ? lower(el.type) : '',
    label: firstName(names),
    name_sources: allNames(names),
    text: ownText(el),
  };
}

// What a caller that did not ask for an identity gets: the same 5 keys, empty, so the
// payload's shape never depends on the flag and `_hit_from` still finds every field it
// declares. Shared and never mutated, like `NO_COVER`.
const NO_IDENT = { role: '', input_type: '', label: '', name_sources: '', text: '' };
