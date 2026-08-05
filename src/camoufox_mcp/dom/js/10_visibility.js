const INTERACTIVE_TAGS = new B.Set([
  'A', 'BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'DETAILS', 'SUMMARY',
]);
const INTERACTIVE_ROLES = new B.Set([
  'button', 'link', 'checkbox', 'radio', 'tab', 'menuitem', 'switch',
  'textbox', 'combobox', 'listbox', 'option', 'slider', 'spinbutton', 'searchbox',
]);
const STRUCTURAL_TAGS = new B.Set([
  'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'P', 'LI', 'TD', 'TH', 'LABEL', 'LEGEND', 'CAPTION',
  'IMG', 'VIDEO', 'AUDIO', 'NAV', 'MAIN', 'HEADER', 'FOOTER', 'SECTION', 'ARTICLE',
  'ASIDE', 'FORM', 'UL', 'OL', 'TABLE', 'THEAD', 'TBODY', 'TFOOT', 'TR',
  'FIELDSET', 'DIALOG', 'FIGURE', 'FIGCAPTION',
]);
const SKIP_TAGS = new B.Set([
  'SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'META', 'LINK', 'BR', 'HR', 'WBR',
  'HEAD', 'TITLE', 'BASE',
]);
const HEADING_TAGS = new B.Set(['H1', 'H2', 'H3', 'H4', 'H5', 'H6']);

const IMPLICIT_ROLES = {
  BUTTON: 'button', SELECT: 'combobox', TEXTAREA: 'textbox', IMG: 'img',
  NAV: 'navigation', MAIN: 'main', HEADER: 'banner', FOOTER: 'contentinfo',
  FORM: 'form', TABLE: 'table', UL: 'list', OL: 'list', LI: 'listitem',
  H1: 'heading', H2: 'heading', H3: 'heading', H4: 'heading', H5: 'heading',
  H6: 'heading', P: 'paragraph', DIALOG: 'dialog', SUMMARY: 'button',
  TD: 'cell', TH: 'columnheader', TR: 'row',
};
const INPUT_ROLES = {
  button: 'button', submit: 'button', reset: 'button', image: 'button',
  file: 'button', checkbox: 'checkbox', radio: 'radio', range: 'slider',
  number: 'spinbutton', search: 'searchbox', email: 'textbox', tel: 'textbox',
  text: 'textbox', url: 'textbox', password: 'textbox',
};

// One computed style per element per operation: the walk asks for it up to three
// times per node, and a fresh Map per call means a restyle is never served stale.
function newStyleCache() {
  return new B.Map();
}

function styleOf(cache, el) {
  let style = B.mapGet.call(cache, el);
  if (style === undefined) {
    style = B.gcs(el);
    B.mapSet.call(cache, el, style);
  }
  return style;
}

function isVisible(cache, el) {
  if (el.nodeType !== 1) return false;
  if (el.getAttribute('aria-hidden') === 'true') return false;
  const style = styleOf(cache, el);
  if (style.display === 'none' || style.visibility === 'hidden') return false;
  if (B.toFloat(style.opacity) === 0) return false;
  const rect = B.gbcr.call(el);
  if (rect.width === 0 && rect.height === 0) return false;
  return true;
}

// Whether an element is worth a line at all: everything it owns itself, plus the
// inherited `cursor: pointer`. The two halves are separate because the walk needs
// the owned half on its own, to decide which single element of a styled clickable
// region gets the cursor credited to it. `ownsInteraction` is declared one file
// later in the bundle, which is the same scope, and function declarations hoist.
function isInteractive(cache, el) {
  if (ownsInteraction(el)) return true;
  return styleOf(cache, el).cursor === 'pointer';
}

// A container that owns a heading is a section in everything but its tag name, and
// dropping it costs that heading under the interactive-only default: 2 blocks below
// it then render as 2 identical buttons with nothing to tell them apart. The document
// body is excluded, being the walk root: every page would otherwise gain a line
// repeating its own <h1>.
function ownsHeading(el) {
  if (el.tagName === 'BODY') return false;
  const children = el.children;
  for (let i = 0; i < children.length; i++) {
    if (HEADING_TAGS.has(children[i].tagName)) return true;
  }
  return false;
}

function shouldInclude(cache, el) {
  if (SKIP_TAGS.has(el.tagName)) return false;
  if (!isVisible(cache, el)) return false;
  if (isInteractive(cache, el)) return true;
  if (STRUCTURAL_TAGS.has(el.tagName)) return true;
  if (el.getAttribute('role')) return true;
  return ownsHeading(el);
}

function roleOf(el) {
  const explicit = el.getAttribute && el.getAttribute('role');
  if (explicit) return explicit.trim().split(/\s+/)[0];
  const tag = el.tagName;
  if (tag === 'A') return el.hasAttribute('href') ? 'link' : '';
  if (tag === 'INPUT') return INPUT_ROLES[(el.type || 'text').toLowerCase()] || 'textbox';
  return IMPLICIT_ROLES[tag] || '';
}

// The classification the fill path dispatches on. Mirrors the input types the
// reference driver assigns rather than types into, minus the date family, which
// this browser accepts real keystrokes for.
function kindOf(el) {
  const tag = el.tagName;
  if (tag === 'SELECT') return 'select';
  if (tag === 'TEXTAREA') return 'text';
  if (tag === 'INPUT') {
    const type = (el.type || 'text').toLowerCase();
    if (type === 'file') return 'file';
    if (type === 'checkbox' || type === 'radio') return 'toggle';
    if (type === 'color' || type === 'range') return 'set';
    return 'text';
  }
  if (el.isContentEditable) return 'rich';
  return 'other';
}
