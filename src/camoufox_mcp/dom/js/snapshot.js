(() => {
  document.querySelectorAll('[data-mcp-uid]').forEach(el => el.removeAttribute('data-mcp-uid'));

  let uidCounter = 0;
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

  function walk(el, depth) {
    const lines = [];
    if (el.nodeType !== 1) return lines;
    if (SKIP_TAGS.has(el.tagName)) return lines;
    if (!isVisible(el)) return lines;

    const included = shouldInclude(el);
    let uid = '';

    if (included && isInteractive(el)) {
      uid = 'e' + uidCounter++;
      el.setAttribute('data-mcp-uid', uid);
    }

    if (included) {
      const indent = '  '.repeat(depth);
      const label = getLabel(el);
      const attrs = getAttributes(el);
      const text = getTextContent(el);

      let line = indent + '[' + label + (uid ? ' ' + uid : '') + (el.disabled ? ' disabled' : '') + ']';
      if (text) line += ' ' + text;
      if (attrs) line += ' ' + attrs;

      lines.push(line);
    }

    for (const child of el.children) {
      lines.push(...walk(child, included ? depth + 1 : depth));
    }

    return lines;
  }

  const title = document.title || '';
  const url = location.href;
  const lines = ['[page] ' + title + ' | ' + url];
  lines.push(...walk(document.body, 1));

  return {
    tree: lines.join('\n'),
    uidCount: uidCounter,
  };
})();
