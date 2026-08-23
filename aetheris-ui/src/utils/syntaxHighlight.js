/**
 * Lightweight syntax highlighter for code blocks.
 * Provides basic regex-based token coloring without external dependencies.
 * Falls back to plain text for unknown languages.
 *
 * Requirements: 18.4 (syntax-highlight code blocks based on language)
 */

const ESCAPE_MAP = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
};

function escapeHtml(str) {
  return str.replace(/[&<>]/g, (ch) => ESCAPE_MAP[ch] || ch);
}

/**
 * Tokenize and colorize a code snippet using simple regex rules.
 */
function colorize(code, rules) {
  let html = escapeHtml(code);

  // Apply rules in order — longest/most specific first
  const sorted = rules.sort((a, b) => b.pattern.source.length - a.pattern.source.length);

  for (const { pattern, className } of sorted) {
    html = html.replace(pattern, (match) => `<span class="${className}">${match}</span>`);
  }

  return html;
}

// ─── Language Definitions ───────────────────────────────────────────

const JS_KEYWORDS = /\b(?:const|let|var|function|return|if|else|for|while|do|switch|case|break|continue|new|this|class|extends|import|from|export|default|async|await|try|catch|finally|throw|typeof|instanceof|in|of|void|delete|yield|true|false|null|undefined)\b/g;
const PY_KEYWORDS = /\b(?:def|class|return|if|elif|else|for|while|try|except|finally|with|as|import|from|raise|assert|lambda|yield|True|False|None|and|or|not|in|is|pass|break|continue|global|nonlocal|del|async|await)\b/g;
const JSON_KEYWORDS = /\b(?:true|false|null)\b/g;
const COMMON_TYPES = /\b(?:String|Number|Boolean|Object|Array|Function|Date|RegExp|Error|Promise|Map|Set|JSON|Math|console|window|document|process|require|module|exports|__dirname|__filename|print|len|range|str|int|float|list|dict|tuple|set|open)\b/g;

const RULES = {
  javascript: [
    { pattern: /\/\/.*$/gm, className: 'sh-comment' },
    { pattern: /\/\*[\s\S]*?\*\//g, className: 'sh-comment' },
    { pattern: /"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`/g, className: 'sh-string' },
    { pattern: /\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b/gi, className: 'sh-number' },
    { pattern: JS_KEYWORDS, className: 'sh-keyword' },
    { pattern: COMMON_TYPES, className: 'sh-type' },
    { pattern: /\b[A-Z][A-Za-z0-9_]*\b/g, className: 'sh-class' },
  ],
  jsx: [
    { pattern: /\/\/.*$/gm, className: 'sh-comment' },
    { pattern: /\/\*[\s\S]*?\*\//g, className: 'sh-comment' },
    { pattern: /"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`/g, className: 'sh-string' },
    { pattern: /\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b/gi, className: 'sh-number' },
    { pattern: JS_KEYWORDS, className: 'sh-keyword' },
    { pattern: COMMON_TYPES, className: 'sh-type' },
    { pattern: /\b[A-Z][A-Za-z0-9_]*\b/g, className: 'sh-class' },
    { pattern: /<(\/)?[A-Z][A-Za-z0-9]*/g, className: 'sh-tag' },
  ],
  typescript: [
    { pattern: /\/\/.*$/gm, className: 'sh-comment' },
    { pattern: /\/\*[\s\S]*?\*\//g, className: 'sh-comment' },
    { pattern: /"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`/g, className: 'sh-string' },
    { pattern: /\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b/gi, className: 'sh-number' },
    { pattern: /\b(?:const|let|var|function|return|if|else|for|while|class|extends|import|from|export|default|async|await|try|catch|interface|type|enum|namespace|declare|readonly|private|protected|public|static|abstract|implements|new|this|throw|typeof|instanceof|in|of|void|delete|yield|true|false|null|undefined)\b/g, className: 'sh-keyword' },
    { pattern: COMMON_TYPES, className: 'sh-type' },
    { pattern: /\b[A-Z][A-Za-z0-9_]*\b/g, className: 'sh-class' },
  ],
  python: [
    { pattern: /#.*$/gm, className: 'sh-comment' },
    { pattern: /"""[\s\S]*?"""|'''[\s\S]*?'''/g, className: 'sh-string' },
    { pattern: /"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'/g, className: 'sh-string' },
    { pattern: /\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b/gi, className: 'sh-number' },
    { pattern: PY_KEYWORDS, className: 'sh-keyword' },
    { pattern: /\b[A-Z][A-Za-z0-9_]*\b/g, className: 'sh-class' },
  ],
  json: [
    { pattern: /"(?:\\.|[^"\\])*"/g, className: 'sh-string' },
    { pattern: JSON_KEYWORDS, className: 'sh-keyword' },
    { pattern: /\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b/gi, className: 'sh-number' },
  ],
  html: [
    { pattern: /<!--[\s\S]*?-->/g, className: 'sh-comment' },
    { pattern: /"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'/g, className: 'sh-string' },
    { pattern: /<(\/)?[a-zA-Z][a-zA-Z0-9\-]*/g, className: 'sh-tag' },
  ],
  css: [
    { pattern: /\/\*[\s\S]*?\*\//g, className: 'sh-comment' },
    { pattern: /"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'/g, className: 'sh-string' },
    { pattern: /@[a-z\-]+/gi, className: 'sh-keyword' },
    { pattern: /\b[a-z\-]+(?=\s*[:{])/gi, className: 'sh-property' },
    { pattern: /\b\d+(?:\.\d+)?(?:px|rem|em|%|vh|vw|s|ms|deg|rad|turn)?\b/gi, className: 'sh-number' },
  ],
  bash: [
    { pattern: /#.*$/gm, className: 'sh-comment' },
    { pattern: /"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'/g, className: 'sh-string' },
    { pattern: /\b(?:if|then|else|elif|fi|for|while|do|done|case|esac|in|function|return|break|continue|shift|exit|export|source|alias|unset|local|readonly|trap|true|false)\b/g, className: 'sh-keyword' },
    { pattern: /\$\{[^}]+\}|\$[A-Za-z_][A-Za-z0-9_]*/g, className: 'sh-variable' },
  ],
  markdown: [
    { pattern: /#+ .+/g, className: 'sh-keyword' },
    { pattern: /\*\*[\s\S]*?\*\*|__[\s\S]*?__/g, className: 'sh-string' },
    { pattern: /`[^`]+`/g, className: 'sh-number' },
    { pattern: /!?\[.*?\]\(.*?\)/g, className: 'sh-type' },
  ],
};

/**
 * Map common language identifiers to our rule set keys.
 */
function normalizeLang(lang) {
  if (!lang) return 'javascript';
  const map = {
    js: 'javascript',
    node: 'javascript',
    'c++': 'javascript', // fallback
    c: 'javascript',
    java: 'javascript', // fallback
    cs: 'javascript', // csharp fallback
    py: 'python',
    ts: 'typescript',
    tsx: 'jsx',
    react: 'jsx',
    shell: 'bash',
    sh: 'bash',
    zsh: 'bash',
    yml: 'json',
    yaml: 'json',
    md: 'markdown',
    '': 'javascript',
  };
  return map[lang] || lang;
}

/**
 * Highlight a raw code string for the given language.
 * Returns raw HTML string (safe to inject into a dangerouslySetInnerHTML).
 */
export function highlight(code, language = '') {
  const lang = normalizeLang(language.toLowerCase().trim());
  const rules = RULES[lang];
  if (!rules) {
    // No rules for this language — return escaped HTML with line breaks preserved
    return escapeHtml(code);
  }
  return colorize(code, rules);
}

/**
 * Return true if we have highlight rules for this language.
 */
export function canHighlight(language = '') {
  const lang = normalizeLang(language.toLowerCase().trim());
  return !!RULES[lang];
}
