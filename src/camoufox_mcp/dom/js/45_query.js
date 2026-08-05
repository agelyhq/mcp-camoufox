// Running a parsed selector against the document, and the `locate` op on top of it.
//
// Index loops and plain index writes throughout, never `for...of` and never an array
// method. This is the path behind `find` and behind every selector-bound click and
// fill, so a page hooking `Array.prototype.filter` or an iterator would otherwise get
// a tally of exactly those calls.
//
// Captured at boot like every other built-in, so a page that patches Node afterwards
// cannot reorder a match set.
const CDP = Node.prototype.compareDocumentPosition;
const FOLLOWING = 4; // Node.DOCUMENT_POSITION_FOLLOWING

// One text test for every caller: `:has-text("...")`, `text=`, and the `text` filter
// of the locate op. All three ask the same question over the same fallback, and
// written separately they drifted into 2 spellings of the same normalisation.
//
// The element's side is always whitespace-collapsed. A quoted `text="..."` is compared
// verbatim against it, which is what makes the quoted form exact; the loose form folds
// case and collapses the needle too.
function textMatches(el, wanted, exact) {
  const text = elementText(el) || collapse(el.textContent);
  if (exact) return text === wanted;
  return text.toLowerCase().indexOf(collapse(wanted).toLowerCase()) !== -1;
}

// A Set built one add at a time. The iterable form of the constructor reads the
// argument's own `Symbol.iterator` AND `Set.prototype.add`, which is the very leak the
// index loops here exist to avoid.
function setOf(els) {
  const set = new B.Set();
  for (let i = 0; i < els.length; i++) set.add(els[i]);
  return set;
}

function indexOfNode(list, node) {
  for (let i = 0; i < list.length; i++) {
    if (list[i] === node) return i;
  }
  return -1;
}

function allElements() {
  const found = B.qsa.call(document, '*');
  const out = [];
  for (let i = 0; i < found.length; i++) {
    const el = found[i];
    if (!SKIP_TAGS.has(el.tagName) && el.tagName !== 'HTML' && el.tagName !== 'BODY') {
      out[out.length] = el;
    }
  }
  return out;
}

// A text= lookup names the smallest element carrying the text, so an ancestor that
// only inherits it from a descendant is dropped. Marking ancestors costs one walk up
// per match; comparing every pair would be quadratic, and a long page matches
// thousands of elements.
function smallestOnly(matched) {
  const set = setOf(matched);
  const outer = new B.Set();
  for (let i = 0; i < matched.length; i++) {
    let parent = matched[i].parentElement;
    while (parent) {
      if (set.has(parent)) outer.add(parent);
      parent = parent.parentElement;
    }
  }
  const out = [];
  for (let i = 0; i < matched.length; i++) {
    if (!outer.has(matched[i])) out[out.length] = matched[i];
  }
  return out;
}

// Both callers read one shape: `els` is the match list and `err` is the CSS engine's
// own complaint, never both.
function queryBranch(branch) {
  let found;
  try {
    found = B.qsa.call(document, branch.css);
  } catch (e) {
    return { els: [], err: String((e && e.message) || e) };
  }
  const els = [];
  for (let i = 0; i < found.length; i++) {
    const el = found[i];
    let keep = true;
    for (let j = 0; keep && j < branch.texts.length; j++) {
      keep = textMatches(el, branch.texts[j], false);
    }
    if (keep) els[els.length] = el;
  }
  return { els: els, err: null };
}

// Merge 2 lists that are each already in document order. querySelectorAll returns
// document order and filtering preserves it, so merging is all a union needs: no
// Array.prototype.sort, and no comparison between elements of the same branch.
function mergeOrdered(left, right) {
  const out = [];
  let i = 0;
  let j = 0;
  while (i < left.length && j < right.length) {
    if (CDP.call(left[i], right[j]) & FOLLOWING) out[out.length] = left[i++];
    else out[out.length] = right[j++];
  }
  while (i < left.length) out[out.length] = left[i++];
  while (j < right.length) out[out.length] = right[j++];
  return out;
}

// A selector list matches the UNION of its branches, deduplicated and in document
// order, exactly as querySelectorAll would if every branch were plain CSS. Each
// branch keeps its own :has-text() filters: they are part of that branch, not a
// condition over the whole list.
function queryParsed(parsed) {
  if (parsed.kind === 'text') {
    const all = allElements();
    const matched = [];
    for (let i = 0; i < all.length; i++) {
      if (textMatches(all[i], parsed.value, parsed.exact)) matched[matched.length] = all[i];
    }
    return { els: smallestOnly(matched), err: null };
  }
  if (parsed.branches.length === 1) return queryBranch(parsed.branches[0]);

  const seen = new B.Set();
  let union = [];
  for (let i = 0; i < parsed.branches.length; i++) {
    const found = queryBranch(parsed.branches[i]);
    if (found.err) return found;
    const fresh = [];
    for (let j = 0; j < found.els.length; j++) {
      const el = found.els[j];
      if (seen.has(el)) continue;
      seen.add(el);
      fresh[fresh.length] = el;
    }
    union = mergeOrdered(union, fresh);
  }
  return { els: union, err: null };
}

function locate(store, a) {
  let candidates;
  if (a.selector) {
    const parsed = parseSelector(a.selector);
    if (parsed.err) return { err: 'bad_selector', msg: parsed.err };
    const found = queryParsed(parsed);
    if (found.err) return { err: 'bad_selector', msg: found.err };
    candidates = found.els;
  } else {
    candidates = allElements();
  }

  const cache = newStyleCache();
  const matched = [];
  for (let i = 0; i < candidates.length; i++) {
    const el = candidates[i];
    if (a.visible && !isVisible(cache, el)) continue;
    if (a.role && roleOf(el) !== a.role) continue;
    if (a.name && lower(accessibleName(el)).indexOf(lower(a.name)) === -1) continue;
    if (a.text && !textMatches(el, a.text, false)) continue;
    matched[matched.length] = el;
  }

  const limit = typeof a.limit === 'number' && a.limit > 0 ? a.limit : matched.length;
  const shown = B.min(limit, matched.length);
  const ids = [];
  const lines = [];
  for (let i = 0; i < shown; i++) {
    const el = matched[i];
    const id = a.mint === false ? '' : mint(store, el);
    ids[ids.length] = id;
    if (a.lines) lines[lines.length] = renderLine({ el: el, depth: 0 }, id);
  }
  return { ok: true, ids: ids, lines: lines, total: matched.length, shown: shown };
}
