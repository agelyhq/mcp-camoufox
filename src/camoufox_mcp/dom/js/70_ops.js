// The user's own script is the ONE thing here allowed to be asynchronous, because
// it is not ours to constrain. The envelope is a top-level promise, which the
// caller's serializer awaits; the Python side bounds it with a real clock.
function evalWithIds(store, a) {
  // Index walk plus plain index writes: `for...of` over the argument array would
  // read the page's own iterator protocol, and `push` its own array method.
  const ids = a.ids;
  const els = [];
  for (let i = 0; i < ids.length; i++) {
    const el = pick(store, ids[i]);
    if (!el) return { ok: false, err: 'unknown', id: ids[i] };
    els[els.length] = el;
  }
  let fn;
  try {
    fn = new B.F('return (' + a.src + ')')();
  } catch (e) {
    return { ok: false, err: 'syntax', msg: String((e && e.message) || e) };
  }
  if (typeof fn !== 'function') return { ok: false, err: 'not_function' };
  // Both promise primitives come from the boot table: `Promise.resolve` and
  // `Promise.prototype.then` are as replaceable as any other global.
  const ran = B.pthen.call(B.presolve(), () => fn.apply(null, els));
  return B.pthen.call(
    ran,
    (value) => ({ ok: true, value: value }),
    (e) => ({ ok: false, err: 'script', msg: String((e && e.message) || e) })
  );
}

const store = {
  v: 1,
  n: 0,
  byId: new B.Map(),
  byEl: new B.WeakMap(),
  ops: {
    capture: guard((a) => {
      sweep(store);
      return buildTree(store, a);
    }),
    locate: guard((a) => {
      sweep(store);
      return locate(store, a);
    }),
    resolve: guard((a) => resolveOne(store, a)),
    // The only op that reads no element id, so it needs neither the store nor a sweep.
    extract: guard((a) => extract(a)),
    scrollTo: guard((a) => scrollTo(store, a)),
    prepareFill: guard((a) => prepareFill(store, a)),
    selectOptions: guard((a) => selectOptions(store, a)),
    selectOption: guard((a) => selectOption(store, a)),
    setFiles: guard((a) => setFiles(store, a)),
    // Guarded like every other op. The wrapper is transparent to the promise this one
    // returns (rejection is already folded into the envelope by `pthen` above); what
    // it catches is a SYNCHRONOUS throw before that promise exists, which would
    // otherwise cross the boundary as a raw driver error the Python side misreads.
    evaluate: guard((a) => evalWithIds(store, a)),
  },
};

return store;
