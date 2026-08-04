((uid) => {
  const el = document.querySelector('[data-mcp-uid="' + uid + '"]');
  if (!el) return { error: 'Element not found. Run take_snapshot to refresh UIDs.' };
  if (el.tagName !== 'SELECT') return { error: 'Element ' + uid + ' is not a <select>.' };

  return {
    options: Array.from(el.options).map((o) => ({
      value: o.value,
      label: (o.label || o.text || '').trim(),
    })),
  };
})
