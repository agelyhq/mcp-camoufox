// Visibility is decided exactly as the snapshot walk decides it, so a state read
// and a selector match can never disagree about the same element.
(...els) => els.map((el) => {
  const style = getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  const hidden = style.display === 'none' || style.visibility === 'hidden' ||
    parseFloat(style.opacity) === 0 || el.getAttribute('aria-hidden') === 'true' ||
    (rect.width === 0 && rect.height === 0);
  const type = String(el.type == null ? '' : el.type).toLowerCase();
  const toggle = type === 'checkbox' || type === 'radio';
  const tag = el.tagName;
  const field = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
  return {
    tag: tag.toLowerCase(),
    ok: true,
    visible: !hidden,
    enabled: 'disabled' in el ? !el.disabled : null,
    checked: toggle ? !!el.checked : null,
    editable: !!el.isContentEditable || (field && !el.disabled && !el.readOnly)
  };
})
