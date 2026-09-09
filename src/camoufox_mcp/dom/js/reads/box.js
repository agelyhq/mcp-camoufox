(...els) => {
  const out = [];
  for (let i = 0; i < els.length; i++) {
    const el = els[i];
    const rect = el.getBoundingClientRect();
    out[out.length] = {
      tag: el.tagName.toLowerCase(), ok: true,
      x: rect.left, y: rect.top, w: rect.width, h: rect.height
    };
  }
  return out;
}
