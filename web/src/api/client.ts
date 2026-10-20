import { z } from 'zod'
import {
  boxSheetSchema,
  boxSchema,
  cashFlowSchema,
  codeSentSchema,
  contributionSchema,
  expenseSchema,
  fundBalancesSchema,
  meSchema,
  pageOf,
  partnerSchema,
  personSchema,
  priceListSchema,
  purchaseSchema,
  rateRowSchema,
  saleSchema,
  settlementSchema,
  stockRowSchema,
  stockSchema,
  summarySchema,
  transferSchema,
} from '@/api/schemas'

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

async function request<S extends z.ZodType>(
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

type Params = Record<string, string | number | boolean | undefined>

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

function range(value: DateRange): Params {
  return { date_from: value.from, date_to: value.to }
}

export const api = {
  people: () => request('/api/auth/people', z.array(personSchema)),
  requestCode: (name: string) => request('/api/auth/code', codeSentSchema, post({ name })),
  login: (name: string, code: string) => request('/api/auth/login', meSchema, post({ name, code })),
  me: () => request('/api/auth/me', meSchema),
  logout: async () => {
    await send('/api/auth/logout', { method: 'POST' })
  },

  balances: () => request('/api/v1/funds/balances', fundBalancesSchema),
  cash: () => request('/api/v1/reports/cash', cashFlowSchema),
  summary: (value: DateRange) =>
    request(withQuery('/api/v1/reports/summary', range(value)), summarySchema),
  prices: () => request('/api/v1/pricing', priceListSchema),
  stock: () => request('/api/v1/inventory/stock', stockSchema),
  ledger: (value: DateRange) =>
    request(withQuery('/api/v1/inventory/ledger', range(value)), z.array(stockRowSchema)),
  purchases: (page: number) =>
    request(withQuery('/api/v1/purchases', { page }), pageOf(purchaseSchema)),
  sales: (page: number, day?: string) =>
    request(withQuery('/api/v1/sales', { page, day }), pageOf(saleSchema)),
  expenses: (page: number) => request(withQuery('/api/v1/expenses', { page }), pageOf(expenseSchema)),
  pendingExpenses: () => request('/api/v1/expenses/pending', z.array(expenseSchema)),
  contributions: (page: number) =>
    request(withQuery('/api/v1/contributions', { page }), pageOf(contributionSchema)),
  transfers: (page: number) =>
    request(withQuery('/api/v1/transfers', { page }), pageOf(transferSchema)),
  settlements: (page: number) =>
    request(withQuery('/api/v1/settlements', { page }), pageOf(settlementSchema)),
  boxes: (page: number, includeSettled: boolean) =>
    request(
      withQuery('/api/v1/boxes', { page, include_settled: includeSettled || undefined }),
      pageOf(boxSchema),
    ),
  boxSheet: (number: number) => request(`/api/v1/boxes/${number}/sheet`, boxSheetSchema),
  rates: (page: number) => request(withQuery('/api/v1/rates', { page }), pageOf(rateRowSchema)),
  partners: () => request('/api/v1/partners', z.array(partnerSchema)),
}
