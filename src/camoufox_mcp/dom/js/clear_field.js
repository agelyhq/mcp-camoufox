((uid) => {
  const el = document.querySelector('[data-mcp-uid="' + uid + '"]');
  if (!el) return { error: 'Element not found. Run take_snapshot to refresh UIDs.' };

  if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
    el.value = '';
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  } else if (el.isContentEditable) {
    el.textContent = '';
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }

  return { cleared: true };
})
