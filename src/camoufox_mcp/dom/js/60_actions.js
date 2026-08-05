const UPLOAD_CHUNK = 65536;

// The built-ins the last two files use, captured at boot for the reason the first
// file states: a page that replaces one of them AFTER this runs does not see the
// calls below. Read off `window` so the capture happens in the same realm the boot
// table used. What this does NOT cover is written out where that table is defined.
const EVENT_CTOR = window.Event;
const FILE_CTOR = window.File;
const TRANSFER_CTOR = window.DataTransfer;
const BYTES_CTOR = window.Uint8Array;
const GET_SELECTION = window.getSelection.bind(window);
const CREATE_RANGE = Document.prototype.createRange;

// Focus the field and place a real selection, then let Python drive trusted key
// input. `el.focus()` is what a native focus helper does anyway, and the resulting
// focus/focusin events are browser-generated.
function prepareFill(store, a) {
  const el = pick(store, a.id);
  if (!el) return { err: 'unknown' };
  const tag = el.tagName.toLowerCase();
  if (el.disabled) return { err: 'disabled', tag: tag };
  if (el.readOnly) return { err: 'readonly', tag: tag };

  if (a.mode === 'set') {
    el.value = a.value;
    el.dispatchEvent(new EVENT_CTOR('input', { bubbles: true }));
    el.dispatchEvent(new EVENT_CTOR('change', { bubbles: true }));
    return { ok: true, tag: tag, had: false, needsEnd: false, typed: false };
  }

  el.focus();
  if (document.activeElement !== el) return { err: 'not_focusable', tag: tag };

  let had = false;
  let needsEnd = false;
  if (tag === 'input' || tag === 'textarea') {
    had = el.value.length > 0;
    try {
      if (a.clear) el.setSelectionRange(0, el.value.length);
      else el.setSelectionRange(el.value.length, el.value.length);
    } catch (e) {
      // email/number/date inputs reject setSelectionRange on this engine.
      if (a.clear) el.select();
      else needsEnd = true;
    }
  } else {
    const selection = GET_SELECTION();
    had = collapse(el.textContent).length > 0;
    if (a.clear) {
      selection.selectAllChildren(el);
    } else {
      selection.removeAllRanges();
      const range = CREATE_RANGE.call(document);
      range.selectNodeContents(el);
      range.collapse(false);
      selection.addRange(range);
    }
  }
  return { ok: true, tag: tag, had: had, needsEnd: needsEnd, typed: true };
}

function selectOptions(store, a) {
  const el = pick(store, a.id);
  if (!el) return { err: 'unknown' };
  if (el.tagName !== 'SELECT') return { err: 'not_select', tag: el.tagName.toLowerCase() };
  // Index walk plus a plain index write, never `for...of` and never an array
  // method: iterating the collection would go through the page's own iterator
  // protocol, which is exactly what capturing built-ins exists to avoid.
  const list = el.options;
  const options = [];
  for (let i = 0; i < list.length; i++) {
    const option = list[i];
    options[options.length] = { value: option.value, label: collapse(option.label || option.text) };
  }
  return { ok: true, options: options };
}

function selectOption(store, a) {
  const el = pick(store, a.id);
  if (!el) return { err: 'unknown' };
  if (el.tagName !== 'SELECT') return { err: 'not_select', tag: el.tagName.toLowerCase() };
  if (el.disabled) return { err: 'disabled', tag: 'select' };
  const list = el.options;
  let found = false;
  for (let i = 0; i < list.length; i++) {
    const option = list[i];
    const wanted = option.value === a.value;
    option.selected = wanted;
    if (wanted) found = true;
  }
  if (!found) return { err: 'no_option', tag: 'select' };
  el.dispatchEvent(new EVENT_CTOR('input', { bubbles: true }));
  el.dispatchEvent(new EVENT_CTOR('change', { bubbles: true }));
  return { ok: true, tag: 'select' };
}

// A uid may point at the input itself, at the <label> that controls it, or at a
// styled wrapper around it.
function fileInputFor(el) {
  if (el.tagName === 'INPUT' && (el.type || '').toLowerCase() === 'file') return el;
  if (el.control && el.control.tagName === 'INPUT' && el.control.type === 'file') return el.control;
  const owner = B.closest.call(el, 'label');
  if (owner && owner.control && owner.control.type === 'file') return owner.control;
  return B.eqsa.call(el, 'input[type="file"]')[0] || null;
}

function decodeBase64(text) {
  const binary = B.atob(text);
  const bytes = new BYTES_CTOR(binary.length);
  for (let offset = 0; offset < binary.length; offset += UPLOAD_CHUNK) {
    const chunk = binary.slice(offset, offset + UPLOAD_CHUNK);
    for (let i = 0; i < chunk.length; i++) bytes[offset + i] = chunk.charCodeAt(i);
  }
  return bytes;
}

// The bytes arrive over the protocol and are attached through the same DataTransfer
// path a driver uses whenever its browser is not on the same machine. The cost is
// stated where it matters: the resulting input/change events are not trusted.
function setFiles(store, a) {
  const el = pick(store, a.id);
  if (!el) return { err: 'unknown' };
  const input = fileInputFor(el);
  if (!input) return { err: 'no_file_input' };
  if (input.webkitdirectory) return { err: 'directory_input' };

  const file = new FILE_CTOR([decodeBase64(a.data)], a.name, { type: a.type });
  const transfer = new TRANSFER_CTOR();
  transfer.items.add(file);
  input.files = transfer.files;
  input.dispatchEvent(new EVENT_CTOR('input', { bubbles: true }));
  input.dispatchEvent(new EVENT_CTOR('change', { bubbles: true }));
  return { ok: true, tag: input.tagName.toLowerCase(), count: input.files.length };
}
