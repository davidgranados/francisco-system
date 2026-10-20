import { keepPreviousData, queryOptions } from '@tanstack/react-query'
import { api, type DateRange } from '@/api/client'

export const queries = {
  people: () => queryOptions({ queryKey: ['people'], queryFn: api.people }),
  me: () => queryOptions({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity }),
  balances: () => queryOptions({ queryKey: ['balances'], queryFn: api.balances }),
  cash: () => queryOptions({ queryKey: ['cash'], queryFn: api.cash }),
  summary: (range: DateRange) =>
    queryOptions({ queryKey: ['summary', range], queryFn: () => api.summary(range) }),
  prices: () => queryOptions({ queryKey: ['prices'], queryFn: api.prices }),
  stock: () => queryOptions({ queryKey: ['stock'], queryFn: api.stock }),
  ledger: (range: DateRange) =>
    queryOptions({ queryKey: ['ledger', range], queryFn: () => api.ledger(range) }),
  purchases: (page: number) =>
    queryOptions({
      queryKey: ['purchases', page],
      queryFn: () => api.purchases(page),
      placeholderData: keepPreviousData,
    }),
  sales: (page: number, day?: string) =>
    queryOptions({
      queryKey: ['sales', page, day ?? null],
      queryFn: () => api.sales(page, day),
      placeholderData: keepPreviousData,
    }),
  expenses: (page: number) =>
    queryOptions({
      queryKey: ['expenses', page],
      queryFn: () => api.expenses(page),
      placeholderData: keepPreviousData,
    }),
  pendingExpenses: () =>
    queryOptions({ queryKey: ['expenses', 'pending'], queryFn: api.pendingExpenses }),
  contributions: (page: number) =>
    queryOptions({
      queryKey: ['contributions', page],
      queryFn: () => api.contributions(page),
      placeholderData: keepPreviousData,
    }),
  transfers: (page: number) =>
    queryOptions({
      queryKey: ['transfers', page],
      queryFn: () => api.transfers(page),
      placeholderData: keepPreviousData,
    }),
  settlements: (page: number) =>
    queryOptions({
      queryKey: ['settlements', page],
      queryFn: () => api.settlements(page),
      placeholderData: keepPreviousData,
    }),
  boxes: (page: number, includeSettled: boolean) =>
    queryOptions({
      queryKey: ['boxes', page, includeSettled],
      queryFn: () => api.boxes(page, includeSettled),
      placeholderData: keepPreviousData,
    }),
  boxSheet: (number: number) =>
    queryOptions({ queryKey: ['boxes', 'sheet', number], queryFn: () => api.boxSheet(number) }),
  rates: (page: number) =>
    queryOptions({
      queryKey: ['rates', page],
      queryFn: () => api.rates(page),
      placeholderData: keepPreviousData,
    }),
  partners: () => queryOptions({ queryKey: ['partners'], queryFn: api.partners }),
}
