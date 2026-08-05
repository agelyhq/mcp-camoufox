// The selector surface, deliberately narrow: native CSS plus the two extensions
// real usage actually relies on. Anything else is refused by name rather than
// silently matching nothing.
//
// This file parses; 45_query.js runs the result against the document. Index loops and
// plain index writes throughout, never `for...of` and never an array method, for the
// reason 00_boot.js states: both resolve a page-owned prototype at call time.
const SELECTOR_HELP = 'supported syntax: plain CSS, :has-text("..."), text=...';
// Not valid CSS anywhere in a selector, so a substring match is safe. It is run
// against the SYNTAX only (see syntaxOnly), never against text a caller quoted.
const UNSUPPORTED_ANYWHERE = [
  ['>>', 'chained engines (>>)'],
  [':visible', ':visible'],
  [':nth-match(', ':nth-match()'],
  [':light(', ':light()'],
];
// Engine prefixes. Matched at the head of a branch ONLY: `[role=button]` and
// `[data-testid="x"]` are ordinary CSS and must keep working.
const UNSUPPORTED_PREFIX = [
  ['role=', 'the role= engine'],
  ['nth=', 'the nth= engine'],
  ['xpath=', 'the xpath= engine'],
  ['id=', 'the id= engine'],
  ['data-testid=', 'the data-testid= engine (use [data-testid="..."])'],
];
const HAS_TEXT = ':has-text(';
const TEXT_ENGINE = /^text\s*=/;

function unquote(raw) {
  const value = raw.trim();
  if (value.length >= 2) {
    const first = value[0];
    if ((first === '"' || first === "'") && value[value.length - 1] === first) {
      return { value: value.slice(1, -1).replace(/\\(.)/g, '$1'), exact: true };
    }
  }
  return { value: value, exact: false };
}

// Split a selector list on its TOP-LEVEL commas. A comma inside quotes, brackets or
// parentheses belongs to its branch, so `[data-x="a,b"]` and `:has-text("a, b")` are
// one branch each.
function splitBranches(selector) {
  const parts = [];
  let start = 0;
  let depth = 0;
  let quote = '';
  for (let i = 0; i < selector.length; i++) {
    const ch = selector[i];
    if (quote) {
      if (ch === '\\') i++;
      else if (ch === quote) quote = '';
    } else if (ch === '"' || ch === "'") {
      quote = ch;
    } else if (ch === '(' || ch === '[') {
      depth++;
    } else if (ch === ')' || ch === ']') {
      if (depth > 0) depth--;
    } else if (ch === ',' && depth === 0) {
      parts[parts.length] = selector.slice(start, i);
      start = i + 1;
    }
  }
  parts[parts.length] = selector.slice(start);
  return parts;
}

// Pull the :has-text(...) clauses out of ONE branch, returning its bare CSS and the
// texts every match of that branch must contain. Quote-aware so a ')' inside the
// argument does not end the clause early.
function splitHasText(branch) {
  const texts = [];
  let rest = branch;
  let css = '';
  for (;;) {
    const at = rest.indexOf(HAS_TEXT);
    if (at === -1) {
      css += rest;
      break;
    }
    css += rest.slice(0, at);
    const open = at + HAS_TEXT.length;
    let cursor = open;
    let quote = '';
    while (cursor < rest.length) {
      const ch = rest[cursor];
      if (quote) {
        if (ch === '\\') cursor++;
        else if (ch === quote) quote = '';
      } else if (ch === '"' || ch === "'") {
        quote = ch;
      } else if (ch === ')') {
        break;
      }
      cursor++;
    }
    if (cursor >= rest.length) {
      return { err: 'unbalanced :has-text(...) in the selector' };
    }
    texts[texts.length] = unquote(rest.slice(open, cursor)).value;
    rest = rest.slice(cursor + 1);
  }
  return { css: css.trim(), texts: texts };
}

// The branch with the CONTENT of every quoted literal removed, quotes kept. The
// unsupported-syntax scan reads this and never the raw string: what a caller quoted
// is data, so `[title="a >> b"]` names no engine.
function syntaxOnly(value) {
  let out = '';
  let quote = '';
  for (let i = 0; i < value.length; i++) {
    const ch = value[i];
    if (quote) {
      if (ch === '\\') i++;
      else if (ch === quote) {
        quote = '';
        out += ch;
      }
    } else {
      if (ch === '"' || ch === "'") quote = ch;
      out += ch;
    }
  }
  return out;
}

function parseBranch(part) {
  const raw = part.trim();
  if (!raw) return { err: 'the selector has an empty branch; ' + SELECTOR_HELP };
  for (let i = 0; i < UNSUPPORTED_PREFIX.length; i++) {
    const entry = UNSUPPORTED_PREFIX[i];
    if (raw.startsWith(entry[0])) {
      return { err: entry[1] + ' is not supported; ' + SELECTOR_HELP };
    }
  }
  const split = splitHasText(raw);
  if (split.err) return split;
  const syntax = syntaxOnly(split.css);
  for (let i = 0; i < UNSUPPORTED_ANYWHERE.length; i++) {
    const entry = UNSUPPORTED_ANYWHERE[i];
    if (syntax.indexOf(entry[0]) !== -1) {
      return { err: entry[1] + ' is not supported; ' + SELECTOR_HELP };
    }
  }
  return { css: split.css || '*', texts: split.texts };
}

function parseSelector(selector) {
  // Trimmed, not whitespace-collapsed: a quoted literal inside the selector must
  // survive verbatim. Text matching normalises both sides on its own.
  const raw = String(selector == null ? '' : selector).trim();
  if (!raw) return { err: 'the selector is empty' };
  if (raw.startsWith('//') || raw.startsWith('(//')) {
    return { err: 'XPath is not supported; ' + SELECTOR_HELP };
  }
  // Everything after `text=` is the text itself, so no selector syntax lives there.
  if (TEXT_ENGINE.test(raw)) {
    const spec = unquote(raw.slice(raw.indexOf('=') + 1));
    if (!spec.value) return { err: 'text= needs a value; ' + SELECTOR_HELP };
    return { kind: 'text', value: spec.value, exact: spec.exact };
  }
  const parts = splitBranches(raw);
  const branches = [];
  for (let i = 0; i < parts.length; i++) {
    const branch = parseBranch(parts[i]);
    if (branch.err) return { err: branch.err };
    branches[branches.length] = branch;
  }
  return { kind: 'css', branches: branches };
}
