/** 统一 API 客户端：解析 { code, message, data } 外壳，把错误转成可展示的 ApiError。 */

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api/v1'

interface Envelope<T> {
  code: number
  message: string
  data: T | null
}

export class ApiError extends Error {
  readonly code: number
  readonly status: number
  readonly detail: unknown

  constructor(message: string, code = 0, status = 0, detail: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.detail = detail
  }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  const isFormData = typeof FormData !== 'undefined' && init.body instanceof FormData
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        // FormData 必须让浏览器自己生成 multipart boundary。
        ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
        ...(init.headers ?? {}),
      },
    })
  } catch {
    throw new ApiError('无法连接后端服务，请确认 API 已启动（scripts\\dev.ps1）')
  }

  const raw = await response.text()
  let payload: Envelope<T> | null = null
  if (raw) {
    try {
      payload = JSON.parse(raw) as Envelope<T>
    } catch {
      payload = null
    }
  }

  if (!response.ok || !payload || payload.code !== 0) {
    throw new ApiError(
      payload?.message ?? `请求失败（HTTP ${response.status}）`,
      payload?.code ?? response.status,
      response.status,
      payload?.data ?? null,
    )
  }

  return payload.data as T
}

export const apiBase = API_BASE
