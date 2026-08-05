// Every length cap the rendering uses, named once. A raw number repeated at 9 call
// sites is 9 chances for one of them to drift away from the concept it encodes.
const NAME_CAP = 80;
// An attribute value rendered inside a `(...)` part: id, placeholder, aria-label, the
// value of a control.
const ATTR_CAP = 40;
// `alt` gets more room: it is a sentence by design, and it is often the only text an
// image control carries.
const ALT_CAP = 60;
// A slice of text used to identify an element rather than to reproduce it: the tail of
// a preview, the selected option of a closed <select>.
const PREVIEW_TEXT_CAP = 30;
const PREVIEW_ATTRS = ['id', 'class', 'role', 'aria-label', 'name', 'data-testid'];
const NAME_ATTRS = ['title', 'alt', 'placeholder'];
// Captured at boot like every other built-in, so a page that replaces it afterwards
// neither sees an aria-labelledby lookup nor answers one with something else.
const GET_BY_ID = Document.prototype.getElementById;
// Shared, never mutated: the empty cover for a caller that renders one element on its
// own line and therefore hides nothing from it.
const NO_COVER = new B.Set();

// Elements whose contents are DATA rather than a label. A <select> named after its own
// options reads "AppleBerry", which is a name nothing has, and a <table> named after
// its rows repeats the whole table on one line. Nothing in here is ever descended into
// when a container collects its own text, so a <select> inside a <label> cannot lend the
// label its list of choices, and nothing in here is ever hoisted either.
const CONTENT_IS_DATA = new B.Set([
  'SELECT', 'DATALIST', 'OPTGROUP', 'INPUT', 'TEXTAREA', 'OUTPUT', 'PROGRESS', 'METER',
  'TABLE', 'THEAD', 'TBODY', 'TFOOT', 'COLGROUP',
  'UL', 'OL', 'DL', 'MENU', 'VIDEO', 'AUDIO', 'IFRAME',
]);

// Containers whose whole subtree is not a name either, for the opposite reason: they
// hold a section of the page rather than a value, so folding all of it into one line
// would print the page twice. They are still not anonymous: with no name of their own
// they hoist one, which is what tells 2 repeated blocks apart.
const CONTENT_IS_SECTION = new B.Set([
  'FORM', 'FIELDSET', 'NAV', 'MAIN', 'HEADER', 'FOOTER', 'SECTION', 'ARTICLE',
  'ASIDE', 'DIALOG', 'BODY',
]);

function isDataContent(el) {
  return CONTENT_IS_DATA.has(el.tagName) || CONTENT_IS_SECTION.has(el.tagName);
}

function collapse(value) {
  return String(value == null ? '' : value).replace(/\s+/g, ' ').trim();
}

function capped(value, max) {
  return value.length > max ? value.slice(0, max) : value;
}

function lower(value) {
  return collapse(value).toLowerCase();
}

// A cover holding one element, so the text collector walks around it. Built fresh per
// call rather than shared and emptied: a leftover entry would hide a subtree from the
// next caller, which is a bug that shows up as a name silently going missing.
function coverOf(el) {
  const cover = new B.Set();
  cover.add(el);
  return cover;
}

// The text of the <label> bound to a form control. It is the only visible name of
// many controls and it lives outside the element. Read through the data-aware
// collector and around the control itself: a <label> WRAPPING a <select> would
// otherwise name it after its own option list, and one wrapping a <textarea> would
// fold whatever the user typed into the name.
function labelText(el) {
  const labels = el.labels;
  if (!labels || labels.length === 0) return '';
  return contentText(labels[0], coverOf(el));
}

// Same rule for the referenced element: an aria-labelledby target holding a control or
// a table names the labelled element after the page's data unless the collector knows
// which of its children carry data.
function labelledByText(el) {
  const by = el.getAttribute('aria-labelledby');
  if (!by) return '';
  const ids = by.split(/\s+/);
  const cover = coverOf(el);
  const parts = [];
  for (let i = 0; i < ids.length; i++) {
    const ref = ids[i] ? GET_BY_ID.call(document, ids[i]) : null;
    if (ref && !isDataContent(ref)) parts[parts.length] = contentText(ref, cover);
  }
  return collapse(parts.join(' '));
}

function attributeName(el) {
  for (let i = 0; i < NAME_ATTRS.length; i++) {
    const value = collapse(el.getAttribute(NAME_ATTRS[i]));
    if (value) return value;
  }
  return '';
}

// The text alternative an image contributes to the text around it. Without it an icon
// control owns no text at all: <button><img alt="Delete row"></button> is a real and
// common shape, and under the interactive-only default the child image gets no line of
// its own either, so the button would be anonymous and unreachable by name.
function altText(el) {
  const tag = el.tagName;
  if (tag === 'IMG' || tag === 'AREA') return collapse(el.getAttribute('alt'));
  if (tag === 'INPUT' && lower(el.type) === 'image') return collapse(el.getAttribute('alt'));
  return '';
}

// The text of `el` minus every subtree the caller renders on its own line, so a nested
// structure prints each piece of text exactly once instead of once per level.
function contentText(el, covered) {
  const parts = [];
  collectOwnText(el, covered || NO_COVER, parts);
  return collapse(parts.join(' '));
}

function collectOwnText(el, covered, out) {
  for (let node = el.firstChild; node; node = node.nextSibling) {
    if (node.nodeType === 3) {
      out[out.length] = node.nodeValue;
    } else if (node.nodeType === 1 && !SKIP_TAGS.has(node.tagName) && !covered.has(node)) {
      const alt = altText(node);
      if (alt) {
        out[out.length] = alt;
      } else if (!isDataContent(node)) {
        collectOwnText(node, covered, out);
      }
    }
  }
}

// The heading that names this container, if it owns one. A nested section is skipped:
// its heading names that section and it renders a line of its own to say so. A heading
// already rendered is skipped too, for the same reason the collector skips covered
// text, and the search then continues rather than giving up.
function firstHeadingText(el, covered) {
  const children = el.children;
  for (let i = 0; i < children.length; i++) {
    const child = children[i];
    if (SKIP_TAGS.has(child.tagName) || covered.has(child) || isDataContent(child)) continue;
    if (HEADING_TAGS.has(child.tagName)) {
      const heading = contentText(child, covered);
      if (heading) return heading;
      continue;
    }
    const nested = firstHeadingText(child, covered);
    if (nested) return nested;
  }
  return '';
}

// Failing a heading, the first piece of text the container carries. One child only:
// the point is to identify the block, not to reprint it.
function firstChildText(el, covered) {
  for (let node = el.firstChild; node; node = node.nextSibling) {
    if (node.nodeType === 3) {
      const own = collapse(node.nodeValue);
      if (own) return own;
    } else if (node.nodeType === 1 && !SKIP_TAGS.has(node.tagName) && !covered.has(node)) {
      const alt = altText(node);
      if (alt) return alt;
      if (!CONTENT_IS_DATA.has(node.tagName)) {
        const own = contentText(node, covered);
        if (own) return own;
      }
    }
  }
  return '';
}

// What an element with no name of its own borrows so an operator can still tell it
// apart from the block beside it. Two <section>s that both render as `[section]` leave
// an agent with 2 identical Edit buttons and no way to choose between them. Text that
// already prints on a line of its own is never borrowed, so nothing is said twice.
function hoistedName(el, covered) {
  const cover = covered || NO_COVER;
  const heading = firstHeadingText(el, cover);
  if (heading) return capped(heading, NAME_CAP);
  return capped(firstChildText(el, cover), NAME_CAP);
}

// The name an operator would read off the screen, computed in the order a real
// accessible-name calculation uses. Direct text children alone are not enough:
// <button><span>Send</span></button> has none. `covered` is the set of elements the
// caller gives their own line; text inside one of them belongs to that line.
function accessibleName(el, covered) {
  if (el.nodeType !== 1) return '';
  const aria = collapse(el.getAttribute('aria-label'));
  if (aria) return capped(aria, NAME_CAP);

  const referenced = labelledByText(el);
  if (referenced) return capped(referenced, NAME_CAP);

  const bound = labelText(el);
  if (bound) return capped(bound, NAME_CAP);

  if (!isDataContent(el)) {
    const own = contentText(el, covered);
    if (own) return capped(own, NAME_CAP);
  }

  const attributed = attributeName(el);
  if (attributed) return capped(attributed, NAME_CAP);

  // Only where a value IS the visible label: a button-like input carries its text
  // there. Everywhere else the value is state, which the attribute list renders, and
  // reading it as a name would print the same string twice.
  if (el.tagName === 'INPUT') return capped(elementText(el), NAME_CAP);

  // A data element stays nameless rather than borrowing: its contents are the very
  // thing that must not become its name.
  return CONTENT_IS_DATA.has(el.tagName) ? '' : hoistedName(el, covered);
}

// What a text-based lookup compares against. Button-like inputs carry their label
// in `value`, not in their (empty) text content.
function elementText(el) {
  const tag = el.tagName;
  if (tag === 'INPUT') {
    const type = (el.type || 'text').toLowerCase();
    if (type === 'button' || type === 'submit' || type === 'reset') {
      return collapse(el.value);
    }
    return '';
  }
  return collapse(el.textContent);
}

// A short, human-readable rendering of an element, used to name whatever blocked a
// pointer action. Deliberately small: the tag, a few identifying attributes, and a
// slice of its text.
function preview(el) {
  if (!el || el.nodeType !== 1) return '<unknown>';
  const tag = el.tagName.toLowerCase();
  let out = '<' + tag;
  for (let i = 0; i < PREVIEW_ATTRS.length; i++) {
    const value = el.getAttribute(PREVIEW_ATTRS[i]);
    if (value) out += ' ' + PREVIEW_ATTRS[i] + '="' + capped(collapse(value), ATTR_CAP) + '"';
  }
  out += '>';
  const text = capped(collapse(el.textContent), PREVIEW_TEXT_CAP);
  return text ? out + text + '</' + tag + '>' : out;
}
