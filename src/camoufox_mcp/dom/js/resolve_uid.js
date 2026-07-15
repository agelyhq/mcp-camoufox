((uid) => {
  const el = document.querySelector('[data-mcp-uid="' + uid + '"]');
  if (!el) return { error: 'Element not found. Run take_snapshot to refresh UIDs.' };

  const rect = el.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) {
    return { error: 'Element has zero size, may be hidden.' };
  }

  return {
    x: rect.x + rect.width / 2,
    y: rect.y + rect.height / 2,
    width: rect.width,
    height: rect.height,
    tag: el.tagName.toLowerCase(),
    type: el.type || null,
    visible: true,
    editable: el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable,
  };
})
