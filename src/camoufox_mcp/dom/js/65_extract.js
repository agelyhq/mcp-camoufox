// The one read whose answer is the document itself rather than an element id.
//
// It belongs here for the reason every other operation does, and for 1 more that is
// about correctness rather than about counting. This read was built as a string in
// Python and evaluated on its own, so `document.querySelector`, `cloneNode`,
// `querySelectorAll` and `NodeList.prototype.forEach` all resolved on the page's own
// prototypes when the call was made. A page replacing the last of those with a no-op
// did not merely see the walk: the pass that drops <script> elements from the clone
// visited nothing, and the caller was handed the scripts it had asked to have removed.
// Every step below goes through the boot table, and the removal is an index loop with
// no array method, like every other file in this bundle.

function scopeOf(a) {
  if (a.selector === null) return B.docEl.call(document);
  return B.qs.call(document, a.selector);
}

// Rendered text, which is what was asked for, with the tree's own text as the only
// honest fallback: `innerText` is an HTMLElement accessor, so an SVG or MathML scope
// has none and there is no rendering for this read to invent.
function textOf(el) {
  if (B.inner) {
    try {
      return B.inner.call(el) || '';
    } catch (e) {
      // Not an HTMLElement. Fall through to the node's text.
    }
  }
  return B.text.call(el) || '';
}

// Scripts come off a COPY, so the live document is never touched: a page whose own
// behaviour changed because something read it would be the loudest leak of all.
// querySelectorAll answers with a static list, so removing as it is walked is safe.
function withoutScripts(el) {
  const copy = B.clone.call(el, true);
  const scripts = B.eqsa.call(copy, 'script');
  for (let i = 0; i < scripts.length; i++) B.drop.call(scripts[i]);
  return copy;
}

// `found: false` rather than an error code: an empty document and a selector that
// matched nothing are the same string to a caller, and which one it was is decided in
// Python, where the wording of that message already lives.
function extract(a) {
  let scope;
  try {
    scope = scopeOf(a);
  } catch (e) {
    // The CSS engine's own complaint about a selector it will not parse.
    return { err: 'bad_selector', msg: String((e && e.message) || e) };
  }
  if (!scope) return { ok: true, found: false };
  if (a.mode === 'text') return { ok: true, found: true, value: textOf(scope) };
  const node = a.strip ? withoutScripts(scope) : scope;
  return { ok: true, found: true, value: B.outer.call(node) };
}
