const NUMBER_LOCALE = 'es-VE'

function decimal(value: number, minimumFractionDigits: number, maximumFractionDigits: number): string {
  return new Intl.NumberFormat(NUMBER_LOCALE, {
    minimumFractionDigits,
    maximumFractionDigits,
    useGrouping: 'always',
  }).format(Math.abs(value))
}

function sign(value: number, digits = 2): string {
  const factor = 10 ** digits
  return Math.round(value * factor) < 0 ? '-' : ''
}

export function formatUsd(value: number): string {
  return `${sign(value)}$ ${decimal(value, 2, 2)}`
}

export function formatBs(value: number): string {
  return `${sign(value)}Bs. ${decimal(value, 2, 2)}`
}

export function formatRate(value: number): string {
  return `Bs. ${decimal(value, 2, 4)}`
}

export function formatInteger(value: number): string {
  return new Intl.NumberFormat(NUMBER_LOCALE, { maximumFractionDigits: 0, useGrouping: 'always' }).format(value)
}

export function formatQuantity(value: number): string {
  return new Intl.NumberFormat(NUMBER_LOCALE, { maximumFractionDigits: 2, useGrouping: 'always' }).format(value)
}

export function formatPercent(fraction: number): string {
  return `${new Intl.NumberFormat(NUMBER_LOCALE, { maximumFractionDigits: 2 }).format(fraction * 100)} %`
}

const WEEKDAYS = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb']

function parseDay(day: string): Date {
  const [year = 0, month = 1, date = 1] = day.split('-').map(Number)
  return new Date(year, month - 1, date)
}

export function formatDay(day: string): string {
  const parsed = parseDay(day)
  const dd = String(parsed.getDate()).padStart(2, '0')
  const mm = String(parsed.getMonth() + 1).padStart(2, '0')
  return `${WEEKDAYS[parsed.getDay()]} ${dd}/${mm}/${parsed.getFullYear()}`
}

export function toDayString(date: Date): string {
  const dd = String(date.getDate()).padStart(2, '0')
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  return `${date.getFullYear()}-${mm}-${dd}`
}

export function today(): string {
  return toDayString(new Date())
}

export function startOfMonth(): string {
  const now = new Date()
  return toDayString(new Date(now.getFullYear(), now.getMonth(), 1))
}

export function pluralize(count: number, singular: string, plural: string): string {
  return `${formatInteger(count)} ${count === 1 ? singular : plural}`
}

export function describeEggAmounts(amounts: {
  boxes: number
  cartons: number
  halves: number
  units: number
}): string {
  const parts = [
    amounts.boxes > 0 ? pluralize(amounts.boxes, 'caja', 'cajas') : null,
    amounts.cartons > 0 ? pluralize(amounts.cartons, 'cartón', 'cartones') : null,
    amounts.halves > 0 ? pluralize(amounts.halves, 'medio cartón', 'medios cartones') : null,
    amounts.units > 0 ? pluralize(amounts.units, 'huevo suelto', 'huevos sueltos') : null,
  ].filter((part): part is string => part !== null)
  return parts.length > 0 ? parts.join(', ') : 'Nada'
}
