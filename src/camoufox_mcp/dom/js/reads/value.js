(...els) => els.map((el) => {
  const tag = el.tagName.toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select' || tag === 'option') {
    return { tag: tag, ok: true, value: String(el.value) };
  }
  if (el.isContentEditable) {
    return { tag: tag, ok: true, value: String(el.textContent == null ? '' : el.textContent) };
  }
  return { tag: tag, ok: false };
})
