// A pointer aimed at the inner span of a button really means the button, and the
// browser reports the span as the topmost hit. Retarget before comparing so a
// legitimate child is never mistaken for an interceptor.
function retargetPointer(el) {
  if (B.matches.call(el, 'input, textarea, select') || el.isContentEditable) return el;
  return B.closest.call(el, 'button, [role=button], a, [role=link]') || el;
}

function hostOf(node) {
  const root = B.rootOf.call(node);
  return (root && root.host) || null;
}

// Walk the stack of elements under the point upward through slots and shadow hosts.
// Reaching the goal means the point belongs to it. Anything else is an interceptor,
// and `root` names the outermost blocking ancestor when the blocker is nested.
//
// Plain index writes and an index search, never `push` or `indexOf`: this runs on
// every hit-tested click, and both are the page's own array methods.
function hitTest(el, x, y) {
  const goal = retargetPointer(el);
  const stack = B.efp.call(document, x, y);
  if (!stack.length) {
    return { blocked: true, by: preview(document.documentElement), root: null };
  }
  const parents = [];
  let hit = stack[0];
  while (hit && hit !== goal && hit !== el) {
    // A <label> standing over its own control activates it, so it is not a blocker.
    if (hit.control && (hit.control === goal || hit.control === el)) break;
    parents[parents.length] = hit;
    hit = hit.assignedSlot || hit.parentElement || hostOf(hit);
  }
  if (hit) return null;

  let root = null;
  let node = goal;
  while (node) {
    const index = indexOfNode(parents, node);
    if (index !== -1) {
      if (index > 1) root = preview(parents[index - 1]);
      break;
    }
    node = node.parentElement || hostOf(node);
  }
  return { blocked: true, by: preview(parents[0]), root: root };
}

// Scroll, measure, classify and hit test in ONE synchronous turn. Waiting is the
// caller's job, on a Python clock: nothing here awaits.
function resolveOne(store, a) {
  const el = pick(store, a.id);
  if (!el) return { err: 'unknown' };
  const tag = el.tagName.toLowerCase();
  if (a.scroll) B.into.call(el, { behavior: 'instant', block: 'center', inline: 'center' });

  const rect = B.gbcr.call(el);
  if (rect.width === 0 && rect.height === 0) return { err: 'zero_size', tag: tag };

  const vw = document.documentElement.clientWidth;
  const vh = document.documentElement.clientHeight;
  const x0 = B.max(0, B.min(rect.left, vw));
  const x1 = B.max(0, B.min(rect.right, vw));
  const y0 = B.max(0, B.min(rect.top, vh));
  const y1 = B.max(0, B.min(rect.bottom, vh));
  if (x1 - x0 <= 0 || y1 - y0 <= 0) return { err: 'offscreen', tag: tag };

  const x = (x0 + x1) / 2;
  const y = (y0 + y1) / 2;
  // Exactly the fields the Python ``Hit`` declares, and nothing else. An accessible
  // name used to travel here too: it costs a subtree walk per call, on every click,
  // every fill and every element screenshot, and no caller ever read it.
  const out = {
    x: x,
    y: y,
    left: rect.left,
    top: rect.top,
    width: rect.width,
    height: rect.height,
    tag: tag,
    kind: kindOf(el),
    disabled: !!el.disabled,
    checked: typeof el.checked === 'boolean' ? el.checked : null,
    intercept: null,
  };
  if (a.hit) out.intercept = hitTest(el, x, y);
  return out;
}

function scrollTo(store, a) {
  const el = pick(store, a.id);
  if (!el) return { err: 'unknown' };
  B.into.call(el, { behavior: 'instant', block: 'center', inline: 'center' });
  return { ok: true, tag: el.tagName.toLowerCase() };
}
