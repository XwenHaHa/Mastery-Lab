/**
 * AI 学习教室的 SSE 客户端（P1.3）。
 *
 * 不依赖 EventSource：生成请求需要 POST + JSON body，并要能用 AbortController 中断。
 * 这里只负责解析 SSE 帧，把 meta / delta / done / error 交给调用方；
 * 持久化、消息合并等业务逻辑留在 ClassroomView。
 */

import { apiBase, ApiError } from './client'
import type { ChatMessage, ChatStatus, TeachingState } from './types'

export interface StreamMeta {
  teaching?: TeachingState
  sessionId: number
  messageId: number
  modelName?: string
}

export interface StreamDone {
  teaching?: TeachingState
  sessionId: number
  messageId: number
  status: ChatStatus
  message: ChatMessage
}

export interface StreamCallbacks {
  onMeta?: (meta: StreamMeta) => void
  onDelta?: (text: string) => void
  onDone?: (payload: StreamDone) => void
  onError?: (message: string, httpStatus?: number) => void
}

function parseEnvelopeError(status: number, raw: string): ApiError {
  try {
    const payload = JSON.parse(raw) as { code?: number; message?: string; data?: unknown }
    return new ApiError(payload.message ?? `请求失败（HTTP ${status}）`, payload.code ?? status, status, payload.data ?? null)
  } catch {
    return new ApiError(`请求失败（HTTP ${status}）`, status, status)
  }
}

export async function streamClassroom(
  path: string,
  body: unknown,
  callbacks: StreamCallbacks,
  signal: AbortSignal,
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${apiBase}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  } catch (error) {
    if (signal.aborted) throw error
    throw new ApiError('无法连接后端服务，请确认 API 已启动')
  }

  if (!response.ok) {
    const raw = await response.text().catch(() => '')
    throw parseEnvelopeError(response.status, raw)
  }
  if (!response.body) {
    throw new ApiError('当前浏览器不支持流式读取')
  }
  if (!response.headers.get('content-type')?.includes('text/event-stream')) {
    throw new ApiError('后端没有返回 SSE 数据，请检查服务或代理配置')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let sawTerminal = false

  const dispatch = (event: string, dataText: string): void => {
    if (signal.aborted || sawTerminal) return
    let data: unknown
    try {
      data = JSON.parse(dataText)
    } catch {
      return
    }
    if (event === 'meta') {
      callbacks.onMeta?.(data as StreamMeta)
      return
    }
    if (event === 'delta') {
      const text = (data as { text?: string }).text ?? ''
      if (text) callbacks.onDelta?.(text)
      return
    }
    if (event === 'done') {
      sawTerminal = true
      callbacks.onDone?.(data as StreamDone)
      return
    }
    if (event === 'error') {
      sawTerminal = true
      const payload = data as { message?: string; httpStatus?: number }
      callbacks.onError?.(payload.message ?? '生成回答时发生未知错误', payload.httpStatus)
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer = (buffer + decoder.decode(value, { stream: true })).replace(/\r\n/g, '\n')
      let separator = buffer.indexOf('\n\n')
      while (separator >= 0) {
        const block = buffer.slice(0, separator)
        buffer = buffer.slice(separator + 2)
        let event = 'message'
        const dataLines: string[] = []
        for (const line of block.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
        }
        if (dataLines.length) dispatch(event, dataLines.join('\n'))
        separator = buffer.indexOf('\n\n')
      }
    }
    if (!sawTerminal && !signal.aborted) {
      callbacks.onError?.('连接意外结束，回答可能没有保存完整；可以点「重新生成」再试')
    }
  } catch (error) {
    if (signal.aborted) throw error
    if (error instanceof ApiError) throw error
    callbacks.onError?.('流式连接中断，已保留当前已经显示的内容')
  } finally {
    reader.releaseLock()
  }
}
