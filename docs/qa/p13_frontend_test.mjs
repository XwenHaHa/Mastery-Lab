import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import test from 'node:test'

const require = createRequire(resolve('apps/web/package.json'))
const ts = require('typescript')

function moduleUrl(path, replacements = {}) {
  let source = readFileSync(path, 'utf8')
  for (const [from, to] of Object.entries(replacements)) source = source.replaceAll(from, to)
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
  return `data:text/javascript;base64,${Buffer.from(output).toString('base64')}`
}

const client = moduleUrl('apps/web/src/api/client.ts', { 'import.meta.env.VITE_API_BASE': "'/api/v1'" })
const { streamClassroom } = await import(moduleUrl('apps/web/src/api/classroomStream.ts', { "'./client'": JSON.stringify(client) }))
const highlight = moduleUrl('apps/web/src/utils/highlight.ts')
const { renderMarkdown } = await import(moduleUrl('apps/web/src/utils/markdown.ts', {
  "'./highlight'": JSON.stringify(highlight),
  "'katex'": JSON.stringify(pathToFileURL(require.resolve('katex')).href),
}))

function responseFrom(chunks) {
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk)
      controller.close()
    },
  }), { headers: { 'Content-Type': 'text/event-stream' } })
}

test('SSE handles every byte boundary, CRLF, UTF-8 and multiline data', async () => {
  const input = 'event: meta\r\ndata: {"messageId":1}\r\n\r\nevent: delta\r\ndata: {"text":"你好"}\r\n\r\nevent: done\r\ndata: {"status":\r\ndata: "completed"}\r\n\r\n'
  const events = []
  globalThis.fetch = async () => responseFrom([...new TextEncoder().encode(input)].map((byte) => Uint8Array.of(byte)))
  await streamClassroom('/test', undefined, {
    onMeta: () => events.push('meta'), onDelta: (text) => events.push(text), onDone: () => events.push('done'), onError: (error) => assert.fail(error),
  }, new AbortController().signal)
  assert.deepEqual(events, ['meta', '你好', 'done'])
})

test('SSE rejects trailing output after terminal event', async () => {
  const events = []
  globalThis.fetch = async () => responseFrom([new TextEncoder().encode('event: done\ndata: {}\n\nevent: delta\ndata: {"text":"stale"}\n\n')])
  await streamClassroom('/test', undefined, { onDone: () => events.push('done'), onDelta: (text) => events.push(text) }, new AbortController().signal)
  assert.deepEqual(events, ['done'])
})

test('Unexpected EOF is reported', async () => {
  let error = ''
  globalThis.fetch = async () => responseFrom([new TextEncoder().encode('event: delta\ndata: {"text":"partial"}\n\n')])
  await streamClassroom('/test', undefined, { onError: (message) => { error = message } }, new AbortController().signal)
  assert.match(error, /意外结束/)
})

test('Abort ignores remaining deltas in the same network chunk', async () => {
  const controller = new AbortController()
  const deltas = []
  globalThis.fetch = async () => responseFrom([new TextEncoder().encode('event: delta\ndata: {"text":"first"}\n\nevent: delta\ndata: {"text":"stale"}\n\n')])
  await streamClassroom('/test', undefined, { onDelta: (text) => { deltas.push(text); controller.abort() } }, controller.signal)
  assert.deepEqual(deltas, ['first'])
})

test('Markdown escapes HTML and unsafe URLs', () => {
  const html = renderMarkdown('<img src=x onerror=alert(1)>\n\n[bad](javascript:alert)\n\n```python\nprint("hello")\n```')
  assert.ok(!html.includes('<img'))
  assert.ok(!html.includes('href="javascript:'))
  assert.ok(html.includes('md-code'))
  assert.ok(html.includes('tok-string'))
})

test('KaTeX renders formulas without trusted HTML', () => {
  const html = renderMarkdown('$x^2$\n\n$$\ny = x + 1\n$$')
  assert.ok(html.includes('katex'))
  assert.ok(html.includes('katex-display'))
  assert.ok(!renderMarkdown('$\\href{javascript:alert(1)}{x}$').includes('href="javascript:'))
})
