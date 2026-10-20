import { keepPreviousData, queryOptions } from '@tanstack/react-query'
import { z } from 'zod'
import { request, withQuery, type DateRange, type Params } from '@/api/client'
import {
  boxSchema,
  boxSheetSchema,
  cashFlowSchema,
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

function dateParams(range: DateRange): Params {
  return { date_from: range.from, date_to: range.to }
}

function paged<S extends z.ZodType>(resource: string, schema: S, page: number, params: Params = {}) {
  return queryOptions({
    queryKey: [resource, page, params],
    queryFn: () => request(withQuery(`/api/v1/${resource}`, { page, ...params }), pageOf(schema)),
    placeholderData: keepPreviousData,
  })
}

export const queries = {
  people: () =>
    queryOptions({ queryKey: ['people'], queryFn: () => request('/api/auth/people', z.array(personSchema)) }),
  me: () =>
    queryOptions({ queryKey: ['me'], queryFn: () => request('/api/auth/me', meSchema), staleTime: Infinity }),
  balances: () =>
    queryOptions({ queryKey: ['balances'], queryFn: () => request('/api/v1/funds/balances', fundBalancesSchema) }),
  cash: () => queryOptions({ queryKey: ['cash'], queryFn: () => request('/api/v1/reports/cash', cashFlowSchema) }),
  summary: (range: DateRange) =>
    queryOptions({
      queryKey: ['summary', range],
      queryFn: () => request(withQuery('/api/v1/reports/summary', dateParams(range)), summarySchema),
    }),
  prices: () => queryOptions({ queryKey: ['prices'], queryFn: () => request('/api/v1/pricing', priceListSchema) }),
  stock: () =>
    queryOptions({ queryKey: ['stock'], queryFn: () => request('/api/v1/inventory/stock', stockSchema) }),
  ledger: (range: DateRange) =>
    queryOptions({
      queryKey: ['ledger', range],
      queryFn: () => request(withQuery('/api/v1/inventory/ledger', dateParams(range)), z.array(stockRowSchema)),
    }),
  purchases: (page: number) => paged('purchases', purchaseSchema, page),
  sales: (page: number, day?: string) => paged('sales', saleSchema, page, { day }),
  expenses: (page: number) => paged('expenses', expenseSchema, page),
  pendingExpenses: () =>
    queryOptions({
      queryKey: ['expenses', 'pending'],
      queryFn: () => request('/api/v1/expenses/pending', z.array(expenseSchema)),
    }),
  contributions: (page: number) => paged('contributions', contributionSchema, page),
  transfers: (page: number) => paged('transfers', transferSchema, page),
  settlements: (page: number) => paged('settlements', settlementSchema, page),
  boxes: (page: number, includeSettled: boolean) =>
    paged('boxes', boxSchema, page, { include_settled: includeSettled || undefined }),
  boxSheet: (number: number) =>
    queryOptions({
      queryKey: ['boxes', 'sheet', number],
      queryFn: () => request(`/api/v1/boxes/${number}/sheet`, boxSheetSchema),
    }),
  rates: (page: number) => paged('rates', rateRowSchema, page),
  partners: () =>
    queryOptions({ queryKey: ['partners'], queryFn: () => request('/api/v1/partners', z.array(partnerSchema)) }),
}
