// The interactivity signals that belong to the element itself. `cursor: pointer` is
// deliberately absent: CSS inherits it, so one styled container hands it to every
// descendant and a card grid would mint a uid per nested node of a single clickable
// region. The walk adds the cursor back for the OUTERMOST element of such a region,
// where it is the only signal there is.
function ownsInteraction(el) {
  if (INTERACTIVE_TAGS.has(el.tagName)) return true;
  const role = el.getAttribute('role');
  if (role && INTERACTIVE_ROLES.has(role)) return true;
  if (el.hasAttribute('tabindex') && B.toInt(el.getAttribute('tabindex'), 10) >= 0) return true;
  if (el.hasAttribute('contenteditable') && el.getAttribute('contenteditable') !== 'false') {
    return true;
  }
  return el.hasAttribute('onclick') || el.hasAttribute('onchange');
}

// The form control a <label> stands for. Two cases matter and they are opposites: the
// control is rendered on its own line, and the label around it is then a pure wrapper
// that would repeat its name one level up; or the control is hidden, which is how
// most styled checkboxes and radios are built, and the label is then the only thing a
// click can reach.
function labelControl(el) {
  if (el.tagName !== 'LABEL') return null;
  return el.control || null;
}

function getLabel(el) {
  const tag = el.tagName.toLowerCase();
  const type = el.getAttribute('type');
  const role = el.getAttribute('role');
  if (tag === 'input' && type) return 'input:' + type;
  if (role) return tag + '[role=' + role + ']';
  return tag;
}

// A part that merely repeats the name is pure payload: `label=` and `placeholder=`
// exist so a control is targetable by the text beside it, and when that text IS the
// name the line already carries it once.
function pushUnlessName(parts, name, key, value, max) {
  const text = collapse(value);
  if (!text || lower(text) === lower(name)) return;
  parts[parts.length] = key + '=' + capped(text, max);
}

// What the label reports on behalf of a control the page hides: an operator sees the
// label, clicks the label, and needs to know what it toggles and where it stands.
function describeControl(parts, control) {
  parts[parts.length] = 'control=' + (roleOf(control) || control.tagName.toLowerCase());
  if (control.name) parts[parts.length] = 'name=' + control.name;
  const type = (control.type || '').toLowerCase();
  if (type === 'checkbox' || type === 'radio') {
    parts[parts.length] = control.checked ? 'checked' : 'unchecked';
  } else if (control.value) {
    parts[parts.length] = 'value=' + capped(collapse(control.value), ATTR_CAP);
  }
  if (control.disabled) parts[parts.length] = 'disabled';
}

function getAttributes(el, name, control) {
  const parts = [];
  const tag = el.tagName;

  if (tag === 'A' && el.href) {
    // The anchor resolves its own href, so this is the same string `new URL(el.href)`
    // would yield without constructing one, and an href the parser rejects reports the
    // empty string instead of throwing. A non-parseable href is not worth reporting.
    const path = B.apath.call(el);
    if (path) parts[parts.length] = 'href=' + path;
  }
  if (tag === 'IMG') pushUnlessName(parts, name, 'alt', el.alt, ALT_CAP);
  pushUnlessName(parts, name, 'placeholder', el.placeholder, ATTR_CAP);
  if (el.name) parts[parts.length] = 'name=' + el.name;
  pushUnlessName(parts, name, 'aria-label', el.getAttribute('aria-label'), ATTR_CAP);

  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') {
    pushUnlessName(parts, name, 'label', labelText(el), ATTR_CAP);
  }
  if (control) describeControl(parts, control);

  if (tag === 'INPUT') {
    const type = el.type;
    if (type === 'checkbox' || type === 'radio') {
      parts[parts.length] = el.checked ? 'checked' : 'unchecked';
    } else if (el.value) {
      pushUnlessName(parts, name, 'value', el.value, ATTR_CAP);
    }
  }
  if (tag === 'SELECT' && el.value) {
    parts[parts.length] = 'value=' + el.value;
    const option = el.options[el.selectedIndex];
    if (option) parts[parts.length] = capped(collapse(option.textContent), PREVIEW_TEXT_CAP);
  }
  if (el.disabled) parts[parts.length] = 'disabled';

  return parts.length > 0 ? '(' + parts.join(', ') + ')' : '';
}

function renderLine(rec, id, covered) {
  const el = rec.el;
  const name = accessibleName(el, covered);
  const attrs = getAttributes(el, name, rec.control || null);
  let line = '  '.repeat(rec.depth) + '[' + getLabel(el) + (id ? ' ' + id : '') + ']';
  if (name) line += ' ' + name;
  if (attrs) line += ' ' + attrs;
  return line;
}

// Pre-order walk collecting one record per included node WITHOUT assigning ids yet.
// Returns { records, hasInteractive } so a parent can learn whether its subtree holds
// any interactive element (used by interactiveOnly). `parentPointer` carries the one
// piece of ancestor context the decision needs, since `cursor` inherits.
//
// Index loops throughout, never `for...of`: iterating an HTMLCollection or an array
// reads an iterator off the page's own prototypes, and the walk runs on every node.
function walk(cache, el, depth, parentPointer) {
  if (el.nodeType !== 1 || SKIP_TAGS.has(el.tagName) || !isVisible(cache, el)) {
    return { records: [], hasInteractive: false };
  }
  const pointer = styleOf(cache, el).cursor === 'pointer';
  const control = labelControl(el);
  const hidden = control !== null && !isVisible(cache, control) ? control : null;
  const wrapper = control !== null && hidden === null && el.contains(control);
  const included = !wrapper && shouldInclude(cache, el);
  const interactive =
    included && (hidden !== null || ownsInteraction(el) || (pointer && !parentPointer));

  const childRecords = [];
  let childHasInteractive = false;
  const childDepth = included ? depth + 1 : depth;
  const children = el.children;
  for (let i = 0; i < children.length; i++) {
    const sub = walk(cache, children[i], childDepth, pointer);
    for (let j = 0; j < sub.records.length; j++) {
      childRecords[childRecords.length] = sub.records[j];
    }
    if (sub.hasInteractive) childHasInteractive = true;
  }

  const records = [];
  if (included) {
    records[0] = {
      el: el,
      depth: depth,
      control: hidden,
      interactive: interactive,
      hasInteractiveDescendant: childHasInteractive,
    };
  }
  for (let i = 0; i < childRecords.length; i++) records[records.length] = childRecords[i];
  return { records: records, hasInteractive: interactive || childHasInteractive };
}

function keepInteractive(records) {
  const kept = [];
  for (let i = 0; i < records.length; i++) {
    const rec = records[i];
    if (rec.interactive || rec.hasInteractiveDescendant) kept[kept.length] = rec;
  }
  return kept;
}

// Clamped here rather than at the call site: a helper that writes `undefined` past the
// end of its input is only ever one caller away from being wrong.
function take(records, limit) {
  const kept = [];
  const end = B.min(limit, records.length);
  for (let i = 0; i < end; i++) kept[i] = records[i];
  return kept;
}

function buildTree(store, a) {
  const cache = newStyleCache();
  const maxNodes = typeof a.maxNodes === 'number' && a.maxNodes > 0 ? a.maxNodes : Infinity;
  const walked = document.body ? walk(cache, document.body, 1, false).records : [];
  const records = a.interactiveOnly === true ? keepInteractive(walked) : walked;
  const total = records.length;
  const shown = total > maxNodes ? take(records, maxNodes) : records;

  // Only the lines actually rendered hide text from their ancestors: a record the cap
  // or the filter dropped prints nowhere, so its text belongs to the nearest ancestor
  // that IS rendered.
  const covered = new B.Set();
  for (let i = 0; i < shown.length; i++) covered.add(shown[i].el);

  const lines = ['[page] ' + (document.title || '') + ' | ' + location.href];
  for (let i = 0; i < shown.length; i++) {
    const rec = shown[i];
    lines[lines.length] = renderLine(rec, rec.interactive ? mint(store, rec.el) : '', covered);
  }
  return {
    ok: true,
    tree: lines.join('\n'),
    totalNodes: total,
    shownNodes: shown.length,
    truncated: total > shown.length,
  };
}
