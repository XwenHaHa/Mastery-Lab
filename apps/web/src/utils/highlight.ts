/**
 * 轻量代码高亮（P1.3 教学回答用）。
 *
 * 不引入 highlight.js / shiki：只需要让 Python 等常见代码块在深色主题下更易读，
 * 且必须在**转义之后**再包标签，保证模型输出里的 HTML 永远不会被执行。
 * 未支持的语言直接返回转义后的纯文本。
 */

const PYTHON = [
  'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await', 'break', 'class', 'continue',
  'def', 'del', 'elif', 'else', 'except', 'finally', 'for', 'from', 'global', 'if', 'import', 'in',
  'is', 'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try', 'while', 'with', 'yield',
  'self', 'cls',
]

const JS = [
  'await', 'async', 'break', 'case', 'catch', 'class', 'const', 'continue', 'debugger', 'default',
  'delete', 'do', 'else', 'export', 'extends', 'finally', 'for', 'from', 'function', 'get', 'if',
  'import', 'in', 'instanceof', 'let', 'new', 'of', 'return', 'set', 'static', 'super', 'switch',
  'this', 'throw', 'try', 'typeof', 'var', 'void', 'while', 'with', 'yield', 'true', 'false', 'null',
  'undefined', 'interface', 'type', 'implements', 'enum', 'public', 'private', 'protected', 'readonly',
]

const BASH = [
  'if', 'then', 'else', 'elif', 'fi', 'for', 'while', 'do', 'done', 'case', 'esac', 'function',
  'in', 'return', 'exit', 'export', 'local', 'echo', 'cd', 'source',
]

const SQL = [
  'select', 'from', 'where', 'and', 'or', 'not', 'insert', 'into', 'values', 'update', 'set',
  'delete', 'create', 'table', 'alter', 'drop', 'join', 'left', 'right', 'inner', 'outer', 'on',
  'group', 'by', 'order', 'having', 'limit', 'offset', 'as', 'distinct', 'count', 'sum', 'avg',
]

const JSON_WORDS = ['true', 'false', 'null']

const KEYWORDS: Record<string, string[]> = {
  python: PYTHON,
  py: PYTHON,
  javascript: JS,
  js: JS,
  typescript: JS,
  ts: JS,
  jsx: JS,
  tsx: JS,
  bash: BASH,
  sh: BASH,
  shell: BASH,
  powershell: BASH,
  ps1: BASH,
  sql: SQL,
  json: JSON_WORDS,
}

const ESCAPES: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (char) => ESCAPES[char])
}

function tokenPattern(language: string): RegExp {
  if (language === 'json') {
    return /("(?:\\.|[^"\\])*")(?=\s*:)|"(?:\\.|[^"\\])*"|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|\b(true|false|null)\b/g
  }
  if (language === 'yaml' || language === 'yml') {
    return /(#[^\n]*)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(-?\d+(?:\.\d+)?)\b|^([A-Za-z_][\w.-]*)(?=\s*:)/gm
  }
  if (language === 'html' || language === 'xml') {
    return /(<!--[\s\S]*?-->)|(<\/?[A-Za-z][^>]*>)/g
  }
  if (language === 'css' || language === 'scss') {
    return /(\/\*[\s\S]*?\*\/)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(-?\d+(?:\.\d+)?(?:px|rem|em|%|s|ms)?)/g
  }

  const words = KEYWORDS[language] ?? []
  const wordPattern = words.length ? `|\\b(${words.join('|')})\\b` : ''
  return new RegExp(
    `(#(?!\\[)[^\\n]*|//[^\\n]*|/\\*[\\s\\S]*?\\*/)` + // 1 comment
      `|("(?:\\\\.|[^"\\\\])*"|'(?:\\\\.|[^'\\\\])*')` + // 2 string
      `|\\b(-?\\d+(?:\\.\\d+)?)\\b` + // 3 number
      wordPattern, // 4 keyword (or capture shifted for json/yaml)
    'g',
  )
}

export function highlightCode(code: string, language: string): string {
  const lang = (language || '').toLowerCase().trim()
  if (!lang || !KEYWORDS[lang] && !['yaml', 'yml', 'html', 'xml', 'css', 'scss'].includes(lang)) {
    return escapeHtml(code)
  }

  const pattern = tokenPattern(lang)
  let out = ''
  let last = 0

  for (const match of code.matchAll(pattern)) {
    const index = match.index ?? 0
    out += escapeHtml(code.slice(last, index))
    const token = match[0]
    if (lang === 'html' || lang === 'xml') {
      out += `<span class="${match[1] ? 'tok-comment' : 'tok-tag'}">${escapeHtml(token)}</span>`
    } else if (lang === 'css' || lang === 'scss') {
      out += `<span class="${match[1] ? 'tok-comment' : match[2] ? 'tok-string' : 'tok-number'}">${escapeHtml(token)}</span>`
    } else if (lang === 'json') {
      if (match[1]) out += `<span class="tok-key">${escapeHtml(token)}</span>`
      else if (match[2]) out += `<span class="tok-number">${escapeHtml(token)}</span>`
      else if (match[3]) out += `<span class="tok-keyword">${escapeHtml(token)}</span>`
      else out += `<span class="tok-string">${escapeHtml(token)}</span>`
    } else if (lang === 'yaml' || lang === 'yml') {
      if (match[1]) out += `<span class="tok-comment">${escapeHtml(token)}</span>`
      else if (match[2]) out += `<span class="tok-string">${escapeHtml(token)}</span>`
      else if (match[3]) out += `<span class="tok-number">${escapeHtml(token)}</span>`
      else out += `<span class="tok-key">${escapeHtml(token)}</span>`
    } else {
      if (match[1]) out += `<span class="tok-comment">${escapeHtml(token)}</span>`
      else if (match[2]) out += `<span class="tok-string">${escapeHtml(token)}</span>`
      else if (match[3]) out += `<span class="tok-number">${escapeHtml(token)}</span>`
      else out += `<span class="tok-keyword">${escapeHtml(token)}</span>`
    }
    last = index + token.length
  }

  out += escapeHtml(code.slice(last))
  return out
}
