// Built-ins captured once, at boot, and called through saved references.
//
// What the capture covers, exactly: the primitives listed in B, plus the handful of
// constructors 60_actions.js captures the same way at the top of its own file. A page
// that replaces any of THOSE after this file runs does not see the calls that go
// through them.
//
// Named, so the boundary is a fact rather than a promise: the Map/WeakMap/WeakRef/Set
// table primitives and the map iterator, the query, geometry, style and scroll entry
// points, the numeric helpers (parseInt, parseFloat, Math.min, Math.max), the promise
// primitives the evaluate envelope is built from, the anchor pathname getter, and the
// event, file, transfer, selection and range constructors the action ops use. No file
// in this bundle uses `for...of` or an Array.prototype method, so no page-owned
// iterator protocol is read either. tests/test_observability_boundary.py hooks a
// sample of these after boot and asserts the page's own tally stays empty.
//
// What the capture does NOT cover, named just as plainly: the per-element accessors
// every walk reads straight off each node (`getAttribute`, `tagName`, `value`,
// `textContent`, `children`, `labels`, ...). They are not routed through B, so a page
// that replaces one of them does count our reads. That is the boundary as it stands;
// this comment states it rather than rounding it up to completeness.
//
// What NO capture can cover: a page that patches a built-in BEFORE our first evaluate.
// Our JS runs in the page's own realm, and there is no realm reachable from the client
// where it would not. That limit is stated in docs/anti-bot.md rather than hidden.
//
// Nothing here is written to the document, to `window`, or as a symbol.
const B = (() => {
  const w = window;
  const mapProto = w.Map.prototype;
  // %MapIteratorPrototype%.next, reached without ever touching Symbol.iterator, so
  // walking our own table below needs no page-resolved iterator protocol.
  const itNext = w.Object.getPrototypeOf(mapProto.entries.call(new w.Map())).next;
  return {
    Map: w.Map,
    WeakMap: w.WeakMap,
    WeakRef: w.WeakRef,
    Set: w.Set,
    F: w.Function,
    mapGet: mapProto.get,
    mapSet: mapProto.set,
    mapDel: mapProto.delete,
    mapEntries: mapProto.entries,
    itNext: itNext,
    wmGet: w.WeakMap.prototype.get,
    wmSet: w.WeakMap.prototype.set,
    deref: w.WeakRef.prototype.deref,
    connected: w.Object.getOwnPropertyDescriptor(w.Node.prototype, 'isConnected').get,
    qsa: Document.prototype.querySelectorAll,
    eqsa: Element.prototype.querySelectorAll,
    efp: Document.prototype.elementsFromPoint,
    gbcr: Element.prototype.getBoundingClientRect,
    matches: Element.prototype.matches,
    closest: Element.prototype.closest,
    rootOf: Node.prototype.getRootNode,
    into: Element.prototype.scrollIntoView,
    gcs: w.getComputedStyle.bind(w),
    atob: w.atob.bind(w),
    // Numeric helpers. The walk calls these once per element per snapshot, which is
    // the hottest path in the product and the one most worth counting from a page.
    toInt: w.parseInt,
    toFloat: w.parseFloat,
    min: w.Math.min,
    max: w.Math.max,
    // The evaluate envelope. `then` is taken off the prototype because that is where
    // a page would patch it; the promise we hand back is then chained by the driver's
    // own serializer, which is outside our realm and outside this boundary.
    presolve: w.Promise.resolve.bind(w.Promise),
    pthen: w.Promise.prototype.then,
    // An anchor already resolves its own href, so reading its `pathname` costs no URL
    // construction, no page-resolved constructor and no try/catch: an href the parser
    // rejects simply reports the empty string.
    apath: w.Object.getOwnPropertyDescriptor(w.HTMLAnchorElement.prototype, 'pathname').get,
  };
})();

// Every op is wrapped in this, so an op NEVER throws across the boundary. A bug in
// our own code then surfaces as a readable error instead of being misclassified as
// a dead execution context by the caller.
function guard(fn) {
  return (a) => {
    try {
      return fn(a);
    } catch (e) {
      return { err: 'internal', msg: String((e && e.message) || e) };
    }
  };
}

// Identity is the live element object: an element already known keeps its id even
// when everything around it moved. The counter never rewinds, so a retired number
// is never handed to a different element.
function mint(store, el) {
  const known = B.wmGet.call(store.byEl, el);
  if (known !== undefined) {
    const ref = B.mapGet.call(store.byId, known);
    if (!ref || B.deref.call(ref) !== el) {
      B.mapSet.call(store.byId, known, new B.WeakRef(el));
    }
    return known;
  }
  const id = 'e' + store.n++;
  B.mapSet.call(store.byId, id, new B.WeakRef(el));
  B.wmSet.call(store.byEl, el, id);
  return id;
}

function pick(store, id) {
  const ref = B.mapGet.call(store.byId, id);
  const el = ref && B.deref.call(ref);
  return el && B.connected.call(el) ? el : null;
}

// Bounds the string keys only. The refs are weak, so nothing is pinned either way.
// The walk uses the captured iterator and plain index writes, never `for...of` and
// never an array method, so replacing any of those on a prototype reveals nothing.
function sweep(store) {
  const dead = [];
  const entries = B.mapEntries.call(store.byId);
  for (let step = B.itNext.call(entries); !step.done; step = B.itNext.call(entries)) {
    const el = B.deref.call(step.value[1]);
    if (!el || !B.connected.call(el)) dead[dead.length] = step.value[0];
  }
  for (let i = 0; i < dead.length; i++) B.mapDel.call(store.byId, dead[i]);
}
