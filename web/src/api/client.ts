import { z } from 'zod'
import { codeSentSchema, meSchema } from '@/api/schemas'

export const MALFORMED_RESPONSE_MESSAGE =
  'El servidor respondió algo que no se entiende. Avise a los desarrolladores.'
export const NETWORK_MESSAGE = 'No hay conexión con el servidor. Revise su internet e intente otra vez.'
const GENERIC_MESSAGE = 'Algo salió mal. Intente otra vez.'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401
}

async function readDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    const detail = z.object({ detail: z.string() }).safeParse(body)
    if (detail.success) return detail.data.detail
  } catch {
    return GENERIC_MESSAGE
  }
  return GENERIC_MESSAGE
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  let response: Response
  try {
    response = await fetch(path, { credentials: 'same-origin', ...init })
  } catch {
    throw new ApiError(0, NETWORK_MESSAGE)
  }
  if (!response.ok) throw new ApiError(response.status, await readDetail(response))
  return response
}

export async function request<S extends z.ZodType>(
  path: string,
  schema: S,
  init?: RequestInit,
): Promise<z.output<S>> {
  const response = await send(path, init)
  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new ApiError(response.status, MALFORMED_RESPONSE_MESSAGE)
  }
  const parsed = schema.safeParse(body)
  if (!parsed.success) throw new ApiError(response.status, MALFORMED_RESPONSE_MESSAGE)
  return parsed.data
}

function post(body: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

export type Params = Record<string, string | number | boolean | undefined>

export function withQuery(path: string, params: Params): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `${path}?${text}` : path
}

export interface DateRange {
  from: string
  to: string
}

export const auth = {
  requestCode: (name: string) => request('/api/auth/code', codeSentSchema, post({ name })),
  login: (name: string, code: string) => request('/api/auth/login', meSchema, post({ name, code })),
  logout: async () => {
    await send('/api/auth/logout', { method: 'POST' })
  },
}
