// A closed select renders its selected option and nothing else, so that, and not
// its empty innerText, is its text.
//
// The selected options are walked by index and concatenated in the loop: `for...of`
// reads the page's own iterator protocol, and `push`/`join` its own array methods. The
// `j ? ', ' : ''` separator reproduces `join(', ')` exactly, empty labels included.
(...els) => {
  const out = [];
  for (let i = 0; i < els.length; i++) {
    const el = els[i];
    const tag = el.tagName.toLowerCase();
    if (tag === 'input' || tag === 'textarea') {
      out[out.length] = { tag: tag, ok: false };
    } else if (tag === 'select') {
      const picked = el.selectedOptions;
      let value = '';
      for (let j = 0; j < picked.length; j++) {
        value += (j ? ', ' : '') + (picked[j].label || picked[j].text);
      }
      out[out.length] = { tag: tag, ok: true, value: value };
    } else {
      const text = el.innerText == null ? el.textContent : el.innerText;
      out[out.length] = { tag: tag, ok: true, value: text == null ? '' : String(text) };
    }
  }
  return out;
}
