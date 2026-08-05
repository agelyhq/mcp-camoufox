(...els) => els.map((el) => {
  const value = el.getAttribute(__NAME__);
  return {
    tag: el.tagName.toLowerCase(), ok: true,
    value: value === null ? '' : String(value), missing: value === null
  };
})
