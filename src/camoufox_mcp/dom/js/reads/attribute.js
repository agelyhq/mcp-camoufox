(...els) => {
  const out = [];
  for (let i = 0; i < els.length; i++) {
    const el = els[i];
    const value = el.getAttribute(__NAME__);
    out[out.length] = {
      tag: el.tagName.toLowerCase(), ok: true,
      value: value === null ? '' : String(value), missing: value === null
    };
  }
  return out;
}
