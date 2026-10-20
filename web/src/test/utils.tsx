import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router'
import { render } from '@testing-library/react'
import { createAppRouter } from '@/app/router'

export interface MockCall {
  method: string
  path: string
  search: URLSearchParams
  body: unknown
}

export interface MockResponse {
  status?: number
  body?: unknown
}

type Handler = MockResponse | ((call: MockCall) => MockResponse | Promise<MockResponse>)

export function mockApi(handlers: Record<string, Handler>) {
  const calls: MockCall[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const call: MockCall = {
        method,
        path: url.pathname,
        search: url.searchParams,
        body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
      }
      calls.push(call)
      const handler = handlers[`${method} ${url.pathname}`]
      if (!handler) return new Response(JSON.stringify({ detail: 'No existe.' }), { status: 404 })
      const result = await (typeof handler === 'function' ? handler(call) : handler)
      const status = result.status ?? 200
      return new Response(status === 204 ? null : JSON.stringify(result.body ?? {}), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return calls
}

export function renderApp(initialPath: string) {
  const history = createMemoryHistory({ initialEntries: [initialPath] })
  const { router, queryClient } = createAppRouter({ history })
  const view = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { router, queryClient, ...view }
}

export const me = { name: 'Francisco', role: 'partner' }

export const balances = {
  capital_usd: '1500.00',
  petty_cash_usd: '230.50',
  savings_usd: '99.00',
  contributed_by_partner: [],
}

export function saleRow(id: number, overrides: Record<string, unknown> = {}) {
  return {
    id,
    day: '2026-10-20',
    rate: '36.5000',
    boxes: 1,
    cartons: 2,
    halves: 0,
    units: 0,
    eggs: 420,
    amount_usd: '12.50',
    amount_bs: '456.25',
    payment_method: 'pago_movil',
    customer: 'Doña Rosa',
    note: null,
    voided: false,
    void_reason: null,
    parts: [],
    ...overrides,
  }
}

export function pageOf(items: unknown[], overrides: Record<string, unknown> = {}) {
  return { items, total: items.length, page: 1, page_size: 20, ...overrides }
}
