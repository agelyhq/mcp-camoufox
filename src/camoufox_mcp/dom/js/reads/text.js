// A closed select renders its selected option and nothing else, so that, and not
// its empty innerText, is its text.
(...els) => els.map((el) => {
  const tag = el.tagName.toLowerCase();
  if (tag === 'input' || tag === 'textarea') return { tag: tag, ok: false };
  if (tag === 'select') {
    const picked = [];
    for (const option of el.selectedOptions) picked.push(option.label || option.text);
    return { tag: tag, ok: true, value: picked.join(', ') };
  }
  const text = el.innerText == null ? el.textContent : el.innerText;
  return { tag: tag, ok: true, value: text == null ? '' : String(text) };
})
