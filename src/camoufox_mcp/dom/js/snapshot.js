((opts) => {
  document.querySelectorAll('[data-mcp-uid]').forEach(el => el.removeAttribute('data-mcp-uid'));

  const maxNodes = (typeof opts.maxNodes === 'number' && opts.maxNodes > 0) ? opts.maxNodes : Infinity;
  const interactiveOnly = opts.interactiveOnly === true;

  const INTERACTIVE_TAGS = new Set([
    'A', 'BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'DETAILS', 'SUMMARY'
  ]);
  const INTERACTIVE_ROLES = new Set([
    'button', 'link', 'checkbox', 'radio', 'tab', 'menuitem', 'switch',
    'textbox', 'combobox', 'listbox', 'option', 'slider', 'spinbutton', 'searchbox'
  ]);
  const STRUCTURAL_TAGS = new Set([
    'H1','H2','H3','H4','H5','H6','P','LI','TD','TH','LABEL','LEGEND','CAPTION',
    'IMG','VIDEO','AUDIO','NAV','MAIN','HEADER','FOOTER','SECTION','ARTICLE',
    'ASIDE','FORM','UL','OL','TABLE','THEAD','TBODY','TFOOT','TR',
    'FIELDSET','DIALOG','FIGURE','FIGCAPTION'
  ]);
  const SKIP_TAGS = new Set([
    'SCRIPT','STYLE','NOSCRIPT','TEMPLATE','META','LINK','BR','HR','WBR'
  ]);

  function isVisible(el) {
    if (el.nodeType !== 1) return false;
    if (el.getAttribute('aria-hidden') === 'true') return false;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    if (parseFloat(style.opacity) === 0) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return false;
    return true;
  }

  function isInteractive(el) {
    if (INTERACTIVE_TAGS.has(el.tagName)) return true;
    const role = el.getAttribute('role');
    if (role && INTERACTIVE_ROLES.has(role)) return true;
    if (el.hasAttribute('tabindex') && parseInt(el.getAttribute('tabindex')) >= 0) return true;
    if (el.hasAttribute('contenteditable') && el.getAttribute('contenteditable') !== 'false') return true;
    if (el.hasAttribute('onclick') || el.hasAttribute('onchange')) return true;
    try {
      if (window.getComputedStyle(el).cursor === 'pointer') return true;
    } catch(e) { /* ignore */ }
    return false;
  }

  function shouldInclude(el) {
    if (SKIP_TAGS.has(el.tagName)) return false;
    if (!isVisible(el)) return false;
    if (isInteractive(el)) return true;
    if (STRUCTURAL_TAGS.has(el.tagName)) return true;
    if (el.getAttribute('role')) return true;
    return false;
  }

  function getLabel(el) {
    const tag = el.tagName.toLowerCase();
    const type = el.getAttribute('type');
    const role = el.getAttribute('role');
    if (tag === 'input' && type) return 'input:' + type;
    if (role) return tag + '[role=' + role + ']';
    return tag;
  }

  function getAttributes(el) {
    const parts = [];
    const tag = el.tagName;

    if (tag === 'A' && el.href) {
      try { parts.push('href=' + new URL(el.href, location.href).pathname); } catch(e) { /* ignore */ }
    }
    if (tag === 'IMG' && el.alt) parts.push('alt=' + el.alt.slice(0, 60));
    if (el.placeholder) parts.push('placeholder=' + el.placeholder.slice(0, 40));
    if (el.name) parts.push('name=' + el.name);
    const ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel) parts.push('aria-label=' + ariaLabel.slice(0, 40));

    if (tag === 'INPUT') {
      const type = el.type;
      if (type === 'checkbox' || type === 'radio') {
        parts.push(el.checked ? 'checked' : 'unchecked');
      } else if (el.value) {
        parts.push('value=' + el.value.slice(0, 40));
      }
    }
    if (tag === 'SELECT' && el.value) {
      const opt = el.options[el.selectedIndex];
      parts.push('value=' + el.value);
      if (opt) parts.push(opt.textContent.trim().slice(0, 30));
    }
    if (el.disabled) parts.push('disabled');

    return parts.length > 0 ? '(' + parts.join(', ') + ')' : '';
  }

  function getTextContent(el) {
    let text = '';
    for (const child of el.childNodes) {
      if (child.nodeType === 3) {
        text += child.textContent;
      }
    }
    return text.trim().replace(/\s+/g, ' ').slice(0, 80);
  }

  // Pre-order walk collecting one record per included node WITHOUT assigning
  // uids yet. Returns { records, hasInteractive } so a parent can learn whether
  // its subtree holds any interactive element (used by interactive_only).
  function walk(el, depth) {
    if (el.nodeType !== 1 || SKIP_TAGS.has(el.tagName) || !isVisible(el)) {
      return { records: [], hasInteractive: false };
    }
    const included = shouldInclude(el);
    const interactive = included && isInteractive(el);
    const childDepth = included ? depth + 1 : depth;

    const childRecords = [];
    let childHasInteractive = false;
    for (const child of el.children) {
      const r = walk(child, childDepth);
      for (const rec of r.records) childRecords.push(rec);
      if (r.hasInteractive) childHasInteractive = true;
    }

    const records = [];
    if (included) {
      records.push({ el, depth, interactive, hasInteractiveDescendant: childHasInteractive });
    }
    for (const rec of childRecords) records.push(rec);
    return { records, hasInteractive: interactive || childHasInteractive };
  }

  function render(rec, uid) {
    const el = rec.el;
    const indent = '  '.repeat(rec.depth);
    const label = getLabel(el);
    const attrs = getAttributes(el);
    const text = getTextContent(el);
    let line = indent + '[' + label + (uid ? ' ' + uid : '') + (el.disabled ? ' disabled' : '') + ']';
    if (text) line += ' ' + text;
    if (attrs) line += ' ' + attrs;
    return line;
  }

  let records = walk(document.body, 1).records;
  if (interactiveOnly) {
    records = records.filter(rec => rec.interactive || rec.hasInteractiveDescendant);
  }
  const totalNodes = records.length;
  const shown = records.length > maxNodes ? records.slice(0, maxNodes) : records;

  let uidCounter = 0;
  const title = document.title || '';
  const url = location.href;
  const lines = ['[page] ' + title + ' | ' + url];
  for (const rec of shown) {
    let uid = '';
    if (rec.interactive) {
      uid = 'e' + uidCounter++;
      rec.el.setAttribute('data-mcp-uid', uid);
    }
    lines.push(render(rec, uid));
  }

  return {
    tree: lines.join('\n'),
    uidCount: uidCounter,
    totalNodes,
    shownNodes: shown.length,
    truncated: totalNodes > shown.length,
  };
})
