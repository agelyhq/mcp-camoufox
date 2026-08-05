(...els) => els.map((el) => {
  const rect = el.getBoundingClientRect();
  return {
    tag: el.tagName.toLowerCase(), ok: true,
    x: rect.left, y: rect.top, w: rect.width, h: rect.height
  };
})
