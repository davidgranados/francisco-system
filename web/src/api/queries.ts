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
  owedExpensesSchema,
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
    queryFn: () => request(withQuery(`/api/v1/${resource}`, { page, ...params }), schema),
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
  purchases: (page: number) => paged('purchases', pageOf(purchaseSchema), page),
  sales: (page: number, day?: string) => paged('sales', pageOf(saleSchema), page, { day }),
  expenses: (page: number) => paged('expenses', pageOf(expenseSchema), page),
  owedExpenses: (page: number) => paged('expenses/owed', owedExpensesSchema, page),
  contributions: (page: number) => paged('contributions', pageOf(contributionSchema), page),
  transfers: (page: number) => paged('transfers', pageOf(transferSchema), page),
  settlements: (page: number) => paged('settlements', pageOf(settlementSchema), page),
  boxes: (page: number, includeSettled: boolean) =>
    paged('boxes', pageOf(boxSchema), page, { include_settled: includeSettled || undefined }),
  boxSheet: (number: number) =>
    queryOptions({
      queryKey: ['boxes', 'sheet', number],
      queryFn: () => request(`/api/v1/boxes/${number}/sheet`, boxSheetSchema),
    }),
  rates: (page: number) => paged('rates', pageOf(rateRowSchema), page),
  partners: () =>
    queryOptions({ queryKey: ['partners'], queryFn: () => request('/api/v1/partners', z.array(partnerSchema)) }),
}
