// An unknown property name reads as an empty string, which is why the enumeration
// is consulted: a real property that happens to compute to nothing must not be
// reported as a typo, and a typo must not be reported as nothing.
(...els) => els.map((el) => {
  const style = getComputedStyle(el);
  const value = style.getPropertyValue(__NAME__);
  const known = value !== '' || Array.prototype.indexOf.call(style, __NAME__) !== -1;
  return { tag: el.tagName.toLowerCase(), ok: known, value: String(value) };
})
