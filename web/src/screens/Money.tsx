import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { queries } from '@/api/queries'
import type { DateRange } from '@/api/client'
import { DateRangeForm } from '@/components/DateRangeForm'
import { FundFlowCard } from '@/components/FundFlowCard'
import { PageHeader } from '@/components/PageHeader'
import { QueryState } from '@/components/QueryState'
import { Fact, Section } from '@/components/RecordCard'
import { buttonVariants } from '@/components/ui/button'
import { formatBs, formatDay, formatInteger, formatUsd } from '@/lib/format'
import { funds, paymentMethods, paymentMethodLabels } from '@/lib/labels'
import type { CashFlow } from '@/api/schemas'

function FundFlows({ cash }: { cash: CashFlow }) {
  return (
    <ul className="grid gap-4 md:grid-cols-3">
      {funds.map((fund) => (
        <FundFlowCard key={fund} fund={fund} flow={cash[fund]} />
      ))}
    </ul>
  )
}

export function MoneyScreen() {
  const cash = useQuery(queries.cash())
  return (
    <>
      <PageHeader title="Dinero">
        <Link to="/dinero/resumen" className={buttonVariants({ variant: 'default', size: 'lg' })}>
          Resumen de un período
        </Link>
      </PageHeader>
      <Section title="Cómo se movió cada fondo">
        <QueryState query={cash}>{(data) => <FundFlows cash={data} />}</QueryState>
      </Section>
    </>
  )
}

export function SummaryScreen({
  range,
  onRange,
}: {
  range: DateRange
  onRange: (range: DateRange) => void
}) {
  const summary = useQuery(queries.summary(range))
  return (
    <>
      <PageHeader title="Resumen de un período" back={{ to: '/dinero', label: 'Dinero' }} />
      <DateRangeForm key={`${range.from}|${range.to}`} value={range} onSubmit={onRange} />
      <QueryState query={summary}>
        {(data) => (
          <>
            <p className="mb-6 text-xl">
              Del <strong>{formatDay(data.date_from)}</strong> al <strong>{formatDay(data.date_to)}</strong>
            </p>
            <Section title="Ventas">
              <dl className="grid gap-2 rounded-xl border-2 bg-card p-4">
                <Fact label="Cantidad de ventas">{formatInteger(data.sales_count)}</Fact>
                <Fact label="Huevos vendidos">{formatInteger(data.eggs_sold)}</Fact>
                <Fact label="Total en dólares">{formatUsd(data.sales_usd)}</Fact>
                <Fact label="Total en bolívares">{formatBs(data.sales_bs)}</Fact>
                {paymentMethods
                  .filter((method) => data.sales_by_payment_method[method] !== undefined)
                  .map((method) => (
                    <Fact key={method} label={paymentMethodLabels[method]}>
                      {formatUsd(data.sales_by_payment_method[method] ?? 0)}
                    </Fact>
                  ))}
              </dl>
            </Section>
            <Section title="Huevos perdidos">
              <dl className="grid gap-2 rounded-xl border-2 bg-card p-4">
                <Fact label="Rotos">{formatInteger(data.broken_eggs)}</Fact>
                <Fact label="Regalados">{formatInteger(data.gifted_eggs)}</Fact>
                <Fact label="Faltantes al contar">{formatInteger(data.shrinkage_eggs)}</Fact>
              </dl>
            </Section>
            <Section title="Compras, gastos y cierres">
              <dl className="grid gap-2 rounded-xl border-2 bg-card p-4">
                <Fact label="Cajas compradas">{formatInteger(data.boxes_bought)}</Fact>
                <Fact label="Gastado en compras">{formatUsd(data.purchases_usd)}</Fact>
                <Fact label="Gastos (salieron de la caja chica)">{formatUsd(data.expenses_usd)}</Fact>
                <Fact label="Falta devolver a socios">{formatUsd(data.pending_reimbursement_usd)}</Fact>
                <Fact label="Ganancia repartida en cierres">{formatUsd(data.settlements_net_usd)}</Fact>
              </dl>
            </Section>
            <Section title="Cómo se movió cada fondo">
              <FundFlows cash={data.cash} />
            </Section>
          </>
        )}
      </QueryState>
    </>
  )
}
