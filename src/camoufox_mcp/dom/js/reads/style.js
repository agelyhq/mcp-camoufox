// An unknown property name reads as an empty string, which is why the enumeration
// is consulted: a real property that happens to compute to nothing must not be
// reported as a typo, and a typo must not be reported as nothing.
//
// The enumeration is walked by index rather than through `Array.prototype.indexOf.call`,
// which named the page's own prototype outright: a page that replaces it decides whether
// a caller is told their property name is a typo. `style.length` and `style[j]` are the
// declaration's own indexed accessors and match the same exact, case-sensitive way.
(...els) => {
  const out = [];
  for (let i = 0; i < els.length; i++) {
    const el = els[i];
    const style = getComputedStyle(el);
    const value = style.getPropertyValue(__NAME__);
    let known = value !== '';
    for (let j = 0; !known && j < style.length; j++) known = style[j] === __NAME__;
    out[out.length] = { tag: el.tagName.toLowerCase(), ok: known, value: String(value) };
  }
  return out;
}
