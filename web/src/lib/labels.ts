export const paymentMethods = ['efectivo_usd', 'efectivo_bs', 'pago_movil', 'punto'] as const
export type PaymentMethod = (typeof paymentMethods)[number]

export const boxStatuses = ['stocked', 'open', 'finished', 'settled'] as const
export type BoxStatus = (typeof boxStatuses)[number]

export const funds = ['capital', 'petty_cash', 'savings'] as const
export type Fund = (typeof funds)[number]

export const transferKinds = ['between_funds', 'contribution_return', 'profit_withdrawal'] as const
export type TransferKind = (typeof transferKinds)[number]

export const rateSources = ['bcv_api', 'manual'] as const
export type RateSource = (typeof rateSources)[number]

export const fundMoveKinds = [
  'contribution',
  'purchase',
  'sale',
  'expense',
  'reimbursement',
  'returned_to_capital',
  'reinvestment',
  'reserve',
  'distribution',
  'between_funds',
  'contribution_return',
  'profit_withdrawal',
] as const
export type FundMoveKind = (typeof fundMoveKinds)[number]

export const paymentMethodLabels: Record<PaymentMethod, string> = {
  efectivo_usd: 'Efectivo en dólares',
  efectivo_bs: 'Efectivo en bolívares',
  pago_movil: 'Pago móvil',
  punto: 'Punto de venta',
}

export const boxStatusLabels: Record<BoxStatus, string> = {
  stocked: 'Guardada',
  open: 'Abierta',
  finished: 'Terminada',
  settled: 'En un cierre',
}

export const fundLabels: Record<Fund, string> = {
  capital: 'Capital',
  petty_cash: 'Caja chica',
  savings: 'Ahorros',
}

export const transferKindLabels: Record<TransferKind, string> = {
  between_funds: 'Entre fondos',
  contribution_return: 'Devolución de aporte',
  profit_withdrawal: 'Retiro de ganancias',
}

export const rateSourceLabels: Record<RateSource, string> = {
  bcv_api: 'Banco Central (BCV)',
  manual: 'Puesta a mano',
}

export const fundMoveKindLabels: Record<FundMoveKind, string> = {
  contribution: 'Aportes de los socios',
  purchase: 'Compras de cajas',
  sale: 'Ventas',
  expense: 'Gastos',
  reimbursement: 'Devoluciones a socios por gastos',
  returned_to_capital: 'Dinero para la próxima caja',
  reinvestment: 'Reinversión',
  reserve: 'Reserva para ahorros',
  distribution: 'Utilidades de los socios',
  between_funds: 'Traspasos entre fondos',
  contribution_return: 'Devoluciones de aportes',
  profit_withdrawal: 'Retiros de ganancias',
}
