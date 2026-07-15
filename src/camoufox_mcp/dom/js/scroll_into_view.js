((uid) => {
  const el = document.querySelector('[data-mcp-uid="' + uid + '"]');
  if (!el) return { error: 'Element not found. Run take_snapshot to refresh UIDs.' };

  el.scrollIntoView({ behavior: 'instant', block: 'center' });
  return { scrolled: true };
})
