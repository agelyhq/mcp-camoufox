((uid) => {
  const el = document.querySelector('[data-mcp-uid="' + uid + '"]');
  if (!el) return { error: 'Element not found. Run take_snapshot to refresh UIDs.' };

  const input = el.tagName === 'INPUT' && el.type === 'file'
    ? el
    : el.querySelector('input[type="file"]');

  if (!input) return { error: 'No file input found at element ' + uid + '.' };

  return { selector: '[data-mcp-uid="' + uid + '"]' + (input === el ? '' : ' input[type="file"]') };
})
