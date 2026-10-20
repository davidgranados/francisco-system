import { z } from 'zod'
import {
  boxStatuses,
  fundMoveKinds,
  paymentMethods,
  rateSources,
  transferKinds,
} from '@/lib/labels'

const money = z
  .union([z.number(), z.string().regex(/^-?\d+(\.\d+)?$/)])
  .transform((value) => Number(value))

const day = z.string().regex(/^\d{4}-\d{2}-\d{2}$/)
const paymentMethod = z.enum(paymentMethods)
const boxStatus = z.enum(boxStatuses)
const fund = z.enum(['capital', 'petty_cash', 'savings'])
const transferKind = z.enum(transferKinds)

export function pageOf<T extends z.ZodType>(item: T) {
  return z.object({
    items: z.array(item),
    total: z.number().int(),
    page: z.number().int(),
    page_size: z.number().int().positive(),
  })
}

export const personSchema = z.object({ name: z.string() })
export const meSchema = z.object({ name: z.string(), role: z.enum(['partner', 'developer']) })
export const codeSentSchema = z.object({ expires_in_seconds: z.number() })

export const boxSchema = z.object({
  number: z.number().int(),
  status: boxStatus,
  purchase_day: day,
  cost_usd: money,
  box_price: money,
  carton_price: money,
  half_price: money,
  unit_price: money,
  remaining_eggs: z.number().int(),
  opened_on: day.nullable(),
  finished_on: day.nullable(),
})

export const purchaseSchema = z.object({
  id: z.number().int(),
  day,
  supplier: z.string().nullable(),
  box_count: z.number().int(),
  cost_per_box_usd: money,
  rate: money,
  total_usd: money,
  total_bs: money,
  payment_method: paymentMethod,
  note: z.string().nullable(),
  voided: z.boolean(),
  void_reason: z.string().nullable(),
  boxes: z.array(boxSchema),
})

export const saleSchema = z.object({
  id: z.number().int(),
  day,
  rate: money,
  boxes: z.number().int(),
  cartons: z.number().int(),
  halves: z.number().int(),
  units: z.number().int(),
  eggs: z.number().int(),
  amount_usd: money,
  amount_bs: money,
  payment_method: paymentMethod,
  customer: z.string().nullable(),
  note: z.string().nullable(),
  voided: z.boolean(),
  void_reason: z.string().nullable(),
  parts: z.array(
    z.object({ box_number: z.number().int(), eggs: z.number().int(), amount_usd: money }),
  ),
})

export const expenseSchema = z.object({
  id: z.number().int(),
  day,
  concept: z.string(),
  amount_usd: money,
  rate: money,
  amount_bs: money,
  paid_by_partner: z.string().nullable(),
  reimbursed_on: day.nullable(),
  settled: z.boolean(),
})

export const contributionSchema = z.object({
  id: z.number().int(),
  partner: z.string(),
  day,
  amount_usd: money,
  note: z.string().nullable(),
})

export const transferSchema = z.object({
  id: z.number().int(),
  day,
  kind: transferKind,
  from_fund: fund,
  to_fund: fund.nullable(),
  partner: z.string().nullable(),
  amount_usd: money,
  note: z.string().nullable(),
  voided: z.boolean(),
  void_reason: z.string().nullable(),
})

const boxProfitSchema = z.object({
  number: z.number().int(),
  cost_usd: money,
  next_box_number: z.number().int(),
  next_box_cost_usd: money,
  difference_usd: money,
  final_cost_usd: money,
  sales_usd: money,
  profit_usd: money,
  broken_eggs: z.number().int(),
  broken_loss_usd: money,
  broken_percent: money,
})

export const settlementSchema = z.object({
  id: z.number().int(),
  day,
  boxes: z.array(boxProfitSchema),
  sales_usd: money,
  box_profit_usd: money,
  expenses: z.array(expenseSchema),
  expenses_usd: money,
  reserve_usd: money,
  reinvest_usd: money,
  net_profit_usd: money,
  shares: z.array(z.object({ partner: z.string(), share: money, amount_usd: money })),
  shares_total_usd: money,
  rate: money,
  rate_stale: z.boolean(),
  amount_bs: money,
  next_box_money_usd: money,
  reimbursements: z.array(z.object({ partner: z.string(), amount_usd: money })),
  petty_cash_after_usd: money,
  capital_after_usd: money,
  savings_after_usd: money,
  note: z.string().nullable(),
})

export const boxSheetSchema = z.object({
  box: boxSchema,
  egg_cost_usd: money,
  rows: z.array(
    z.object({
      day,
      rate: money.nullable(),
      boxes: z.number().int(),
      cartons: z.number().int(),
      halves: z.number().int(),
      units: z.number().int(),
      shared_sale_eggs: z.number().int(),
      broken: z.number().int(),
      other_losses: z.number().int(),
      eggs: z.number().int(),
      amount_usd: money,
      amount_bs: money,
      payment_methods: z.array(paymentMethod),
    }),
  ),
  total_eggs: z.number().int(),
  total_broken: z.number().int(),
  total_sales_usd: money,
  profit: boxProfitSchema.nullable(),
})

export const stockSchema = z.object({
  total_eggs: z.number().int(),
  boxes_equivalent: money,
  boxes: z.array(boxSchema),
  average_box_cost_usd: money.nullable(),
  average_egg_cost_usd: money.nullable(),
})

export const stockRowSchema = z.object({
  day,
  description: z.string(),
  entered: z.number().int(),
  sold: z.number().int(),
  broken: z.number().int(),
  other_losses: z.number().int(),
  remaining_eggs: z.number().int(),
  remaining_boxes: money,
  counted: z.number().int().nullable(),
  difference: z.number().int().nullable(),
})

const fundFlowSchema = z.object({
  opening_usd: money,
  entered_usd: money,
  left_usd: money,
  closing_usd: money,
  by_kind: z.partialRecord(z.enum(fundMoveKinds), money),
})

export const cashFlowSchema = z.object({
  capital: fundFlowSchema,
  petty_cash: fundFlowSchema,
  savings: fundFlowSchema,
})

export const fundBalancesSchema = z.object({
  capital_usd: money,
  petty_cash_usd: money,
  savings_usd: money,
  contributed_by_partner: z.array(z.object({ partner: z.string(), amount_usd: money })),
})

export const summarySchema = z.object({
  date_from: day,
  date_to: day,
  sales_count: z.number().int(),
  eggs_sold: z.number().int(),
  sales_usd: money,
  sales_bs: money,
  sales_by_payment_method: z.partialRecord(paymentMethod, money),
  broken_eggs: z.number().int(),
  gifted_eggs: z.number().int(),
  shrinkage_eggs: z.number().int(),
  boxes_bought: z.number().int(),
  purchases_usd: money,
  expenses_usd: money,
  pending_reimbursement_usd: money,
  settlements_net_usd: money,
  cash: cashFlowSchema,
})

const priceLineSchema = z.object({ usd: money, bs: money })

export const priceListSchema = z.object({
  day,
  rate: money,
  rate_stale: z.boolean(),
  box_number: z.number().int(),
  box: priceLineSchema,
  carton: priceLineSchema,
  half: priceLineSchema,
  unit: priceLineSchema,
  notice: z.string().nullable(),
})

export const partnerSchema = z.object({
  name: z.string(),
  share: money,
  telegram_user_id: z.number().nullable(),
  active: z.boolean(),
})

export const rateRowSchema = z.object({
  day,
  rate: money,
  source: z.enum(rateSources),
})

export type Me = z.output<typeof meSchema>
export type Box = z.output<typeof boxSchema>
export type Purchase = z.output<typeof purchaseSchema>
export type Sale = z.output<typeof saleSchema>
export type Expense = z.output<typeof expenseSchema>
export type Contribution = z.output<typeof contributionSchema>
export type Transfer = z.output<typeof transferSchema>
export type Settlement = z.output<typeof settlementSchema>
export type BoxSheet = z.output<typeof boxSheetSchema>
export type Stock = z.output<typeof stockSchema>
export type StockRow = z.output<typeof stockRowSchema>
export type CashFlow = z.output<typeof cashFlowSchema>
export type FundFlow = CashFlow['capital']
export type FundBalances = z.output<typeof fundBalancesSchema>
export type PeriodSummary = z.output<typeof summarySchema>
export type PriceList = z.output<typeof priceListSchema>
export type Partner = z.output<typeof partnerSchema>
export type RateRow = z.output<typeof rateRowSchema>
export type Page<T> = { items: T[]; total: number; page: number; page_size: number }
