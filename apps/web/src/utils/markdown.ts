/**
 * 极简 Markdown 渲染器（知识点正文用）。
 *
 * 为什么不用 marked/markdown-it：P1.2 只需要「安全地展示教材里的常见 Markdown」，
 * 引一个第三方渲染器 + 消毒库会带来两个新依赖和持续的 XSS 面；
 * 这里的策略是 **先转义、再按行组装标签**，因此用户/教材里的 HTML 永远不会被当成标签执行。
 *
 * 支持：标题、段落、代码围栏（带语言标识，常见语言有轻量高亮）、行内代码、粗体/斜体/删除线、
 * 有序与无序列表（含一层缩进嵌套）、引用、分隔线、表格、链接、KaTeX 数学公式。
 * 不支持（也不打算支持）：裸 HTML、图片、脚注、Mermaid——出现时按普通文本或代码显示。
 */

import katex from 'katex'

import { highlightCode } from './highlight'

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

/** 只允许 http(s)、mailto、站内相对路径与锚点，其他（例如 javascript:）降级成纯文本。 */
function safeHref(raw: string): string | null {
  const href = raw.trim()
  if (!href) return null
  if (/^(https?:\/\/|mailto:)/i.test(href)) return href
  if (href.startsWith('/') || href.startsWith('./') || href.startsWith('../') || href.startsWith('#')) return href
  return null
}

/** 用 KaTeX 渲染公式；失败时返回 null，由调用方退回原始文本，绝不把错误 HTML 塞进页面。 */
function renderMath(expression: string, display: boolean): string | null {
  const source = expression.trim()
  if (!source) return null
  try {
    return katex.renderToString(source, {
      displayMode: display,
      throwOnError: false,
      trust: false,
      strict: false,
      output: 'html',
    })
  } catch {
    return null
  }
}

function renderInline(text: string): string {
  // 先摘出行内代码，避免 `$...$` 出现在代码里时被误判成公式
  const codes: string[] = []
  let out = text.replace(/`([^`]+)`/g, (_match, code: string) => {
    codes.push(escapeHtml(code))
    return `\u0000CODE${codes.length - 1}\u0000`
  })

  // 再摘出数学公式：纯数字（如价格 $5）不当公式，避免误伤正常文本
  const maths: string[] = []
  out = out.replace(/\$([^$\n]+)\$/g, (match, expression: string) => {
    if (/^[\d.,\s]+$/.test(expression.trim())) return match
    const html = renderMath(expression, false)
    if (!html) return match
    maths.push(html)
    return `\u0000MATH${maths.length - 1}\u0000`
  })

  out = escapeHtml(out)

  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_match, label: string, href: string) => {
    const safe = safeHref(href)
    if (!safe) return label
    // href 与 label 都来自已转义文本，这里不能再转义一次（会变成 &amp;amp;）
    return `<a href="${safe}" target="_blank" rel="noreferrer noopener">${label}</a>`
  })
  out = out.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  out = out.replace(/__([^_\n]+)__/g, '<strong>$1</strong>')
  out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
  out = out.replace(/~~([^~\n]+)~~/g, '<del>$1</del>')

  out = out.replace(/\u0000CODE(\d+)\u0000/g, (_match, index: string) => `<code>${codes[Number(index)]}</code>`)
  out = out.replace(/\u0000MATH(\d+)\u0000/g, (_match, index: string) => maths[Number(index)])
  return out
}

const FENCE = /^\s*(```|~~~)\s*([\w+#.-]*)\s*$/
const HEADING = /^\s{0,3}(#{1,6})\s+(.*)$/
const HR = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/
const QUOTE = /^\s{0,3}>\s?/
const UL = /^(\s*)[-*+]\s+(.*)$/
const OL = /^(\s*)\d+[.)]\s+(.*)$/
const TABLE = /^\s*\|.*\|\s*$/
const TABLE_DIVIDER = /^\s*\|?[\s:|-]+\|[\s:|-]*$/
const DISPLAY_MATH = /^\s*\$\$/

export function renderMarkdown(source: string): string {
  const lines = (source ?? '').replace(/\r\n?/g, '\n').split('\n')
  const html: string[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]

    if (!line.trim()) {
      index += 1
      continue
    }

    // ---- 块级数学公式 ----
    if (DISPLAY_MATH.test(line)) {
      const body: string[] = []
      const first = line.replace(DISPLAY_MATH, '')
      if (first.trim().endsWith('$$')) {
        body.push(first.trim().slice(0, -2))
        index += 1
      } else {
        if (first.trim()) body.push(first)
        index += 1
        while (index < lines.length) {
          const current = lines[index]
          if (current.trim().endsWith('$$')) {
            body.push(current.trim().slice(0, -2))
            index += 1
            break
          }
          body.push(current)
          index += 1
        }
      }
      const rendered = renderMath(body.join('\n'), true)
      html.push(
        rendered
          ? `<div class="md-math">${rendered}</div>`
          : `<pre class="md-code" data-lang="math"><code>${escapeHtml(body.join('\n'))}</code></pre>`,
      )
      continue
    }

    // ---- 代码围栏 ----
    const fence = line.match(FENCE)
    if (fence) {
      const marker = fence[1]
      const language = fence[2] || 'text'
      const body: string[] = []
      index += 1
      while (index < lines.length && !lines[index].trim().startsWith(marker)) {
        body.push(lines[index])
        index += 1
      }
      index += 1 // 跳过结束围栏（文件被截断时也不会丢内容）
      html.push(
        `<pre class="md-code" data-lang="${escapeHtml(language)}"><code class="lang-${escapeHtml(language)}">${highlightCode(body.join('\n'), language)}</code></pre>`,
      )
      continue
    }

    // ---- 标题 ----
    const heading = line.match(HEADING)
    if (heading) {
      const level = Math.min(heading[1].length + 1, 6) // 正文里的 # 视为二级，避免和页面标题打架
      html.push(`<h${level}>${renderInline(heading[2].trim())}</h${level}>`)
      index += 1
      continue
    }

    // ---- 分隔线 ----
    if (HR.test(line)) {
      html.push('<hr />')
      index += 1
      continue
    }

    // ---- 引用 ----
    if (QUOTE.test(line)) {
      const body: string[] = []
      while (index < lines.length && QUOTE.test(lines[index])) {
        body.push(lines[index].replace(QUOTE, ''))
        index += 1
      }
      html.push(`<blockquote>${renderMarkdown(body.join('\n'))}</blockquote>`)
      continue
    }

    // ---- 表格 ----
    if (TABLE.test(line) && index + 1 < lines.length && TABLE_DIVIDER.test(lines[index + 1])) {
      const rows: string[][] = [splitRow(line)]
      index += 2
      while (index < lines.length && TABLE.test(lines[index])) {
        rows.push(splitRow(lines[index]))
        index += 1
      }
      const [head, ...body] = rows
      const thead = `<thead><tr>${head.map((cell) => `<th>${renderInline(cell)}</th>`).join('')}</tr></thead>`
      const tbody = body.length
        ? `<tbody>${body
            .map((row) => `<tr>${row.map((cell) => `<td>${renderInline(cell)}</td>`).join('')}</tr>`)
            .join('')}</tbody>`
        : ''
      html.push(`<table>${thead}${tbody}</table>`)
      continue
    }

    // ---- 列表 ----
    const ul = line.match(UL)
    const ol = line.match(OL)
    if (ul || ol) {
      const { markup, consumed } = collectList(lines, index)
      html.push(markup)
      index = consumed
      continue
    }

    // ---- 段落 ----
    const paragraph: string[] = []
    while (index < lines.length && lines[index].trim() && !isBlockStart(lines[index])) {
      paragraph.push(lines[index].trim())
      index += 1
    }
    if (paragraph.length) html.push(`<p>${renderInline(paragraph.join(' '))}</p>`)
    else index += 1 // 防御：不认识的块也要前进，避免死循环
  }

  return html.join('\n')
}

function isBlockStart(line: string): boolean {
  return (
    FENCE.test(line) ||
    DISPLAY_MATH.test(line) ||
    HEADING.test(line) ||
    HR.test(line) ||
    QUOTE.test(line) ||
    UL.test(line) ||
    OL.test(line) ||
    TABLE.test(line)
  )
}

function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

/** 收集从 start 开始的一段（可嵌套一层的）列表，返回 HTML 与下一行下标。 */
function collectList(lines: string[], start: number): { markup: string; consumed: number } {
  const ordered = Boolean(lines[start].match(OL))
  const items: { indent: number; text: string; children: string[] }[] = []
  let index = start

  while (index < lines.length) {
    const line = lines[index]
    if (!line.trim()) {
      // 空行后面若还是列表项，则继续；否则结束
      const next = lines[index + 1]
      if (next && (UL.test(next) || OL.test(next))) {
        index += 1
        continue
      }
      break
    }
    const match = line.match(UL) ?? line.match(OL)
    if (!match) {
      // 缩进的续行并入上一项
      if (items.length && /^\s{2,}/.test(line)) {
        items[items.length - 1].text += ` ${line.trim()}`
        index += 1
        continue
      }
      break
    }
    const indent = match[1].length
    const text = match[2]
    if (indent >= 2 && items.length) {
      items[items.length - 1].children.push(`<li>${renderInline(text)}</li>`)
    } else {
      items.push({ indent, text, children: [] })
    }
    index += 1
  }

  const tag = ordered ? 'ol' : 'ul'
  const markup = `<${tag}>${items
    .map((item) => {
      const children = item.children.length ? `<${tag}>${item.children.join('')}</${tag}>` : ''
      return `<li>${renderInline(item.text)}${children}</li>`
    })
    .join('')}</${tag}>`
  return { markup, consumed: index }
}
