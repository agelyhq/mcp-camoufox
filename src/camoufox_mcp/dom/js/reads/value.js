// The value of an <input type=password> is never rendered, here as in the snapshot walk
// (`elidedValue`, 30_walk.js): this record is handed to the model AND kept verbatim as
// the telemetry `result`, which redaction never rewrites. The rule is restated rather
// than shared because a read script is compiled by the Function constructor and runs in
// the page's global scope, where the bundle's own declarations are not in scope.
// The marker is length-preserving, so the field still says how much it holds.
//
// Index loop and plain index writes, like every file of the bundle: `els.map` resolves
// `Array.prototype.map` on the PAGE at call time, so a page that replaces it would both
// count this read and decide what it returns — and what it returns here is whether a
// typed password reaches the model and the log in clear. That is the same defect the
// identity walk had with `Array.prototype.join`.
//
// `el.type` is read as it comes: the IDL attribute is already lowercased (30_walk.js
// says so where it normalises the other path), so folding it again would be one more
// page-resolved call deciding a security answer.
(...els) => {
  const out = [];
  for (let i = 0; i < els.length; i++) {
    const el = els[i];
    const tag = el.tagName.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || tag === 'option') {
      const value = String(el.value);
      const secret = tag === 'input' && el.type === 'password';
      out[out.length] = {
        tag: tag, ok: true,
        value: secret ? '<redacted ' + value.length + ' chars>' : value
      };
    } else if (el.isContentEditable) {
      out[out.length] = {
        tag: tag, ok: true,
        value: String(el.textContent == null ? '' : el.textContent)
      };
    } else {
      out[out.length] = { tag: tag, ok: false };
    }
  }
  return out;
}
