import { queries } from '@/api/queries'
import { PageHeader } from '@/components/PageHeader'
import { PagedList } from '@/components/PagedList'
import { Amounts, Fact, RecordCard } from '@/components/RecordCard'
import { formatDay, formatPercent, formatRate, formatUsd, formatInteger } from '@/lib/format'

export function SettlementsScreen() {
  return (
    <>
      <PageHeader title="Cierres" />
      <PagedList
        options={queries.settlements}
        empty="Todavía no hay cierres."
        renderItem={(settlement) => (
          <RecordCard
            key={settlement.id}
            title={`Cierre del ${formatDay(settlement.day)}`}
            subtitle={
              settlement.boxes.length > 0
                ? `Cajas: ${settlement.boxes.map((box) => box.number).join(', ')}`
                : 'Sin cajas'
            }
            amount={<Amounts usd={settlement.net_profit_usd} bs={settlement.amount_bs} />}
          >
            <Fact label="Ganancia para repartir">{formatUsd(settlement.net_profit_usd)}</Fact>
            {settlement.shares.map((share) => (
              <Fact key={share.partner} label={`${share.partner} (${formatPercent(share.share)})`}>
                {formatUsd(share.amount_usd)}
              </Fact>
            ))}
            <details className="rounded-lg border p-3">
              <summary className="flex min-h-12 cursor-pointer items-center text-lg font-semibold">
                Ver todo el detalle
              </summary>
              <dl className="mt-2 grid gap-2">
                <Fact label="Ventas de las cajas">{formatUsd(settlement.sales_usd)}</Fact>
                <Fact label="Ganancia de las cajas">{formatUsd(settlement.box_profit_usd)}</Fact>
                <Fact label="Gastos">{formatUsd(settlement.expenses_usd)}</Fact>
                <Fact label="A ahorros (reserva)">{formatUsd(settlement.reserve_usd)}</Fact>
                <Fact label="Vuelve al capital (reinversión)">{formatUsd(settlement.reinvest_usd)}</Fact>
                <Fact label="Dinero para la próxima caja">{formatUsd(settlement.next_box_money_usd)}</Fact>
                <Fact label="Tasa del cierre">{formatRate(settlement.rate)}</Fact>
                {settlement.reimbursements.map((item) => (
                  <Fact key={item.partner} label={`Devuelto a ${item.partner}`}>
                    {formatUsd(item.amount_usd)}
                  </Fact>
                ))}
                <Fact label="Capital después del cierre">{formatUsd(settlement.capital_after_usd)}</Fact>
                <Fact label="Caja chica después del cierre">{formatUsd(settlement.petty_cash_after_usd)}</Fact>
                <Fact label="Ahorros después del cierre">{formatUsd(settlement.savings_after_usd)}</Fact>
                {settlement.boxes.map((box) => (
                  <Fact key={box.number} label={`Caja ${box.number}`}>
                    gana {formatUsd(box.profit_usd)}
                    {box.broken_eggs > 0 ? `, ${formatInteger(box.broken_eggs)} rotos` : ''}
                  </Fact>
                ))}
                {settlement.note ? <Fact label="Nota">{settlement.note}</Fact> : null}
              </dl>
            </details>
          </RecordCard>
        )}
      />
    </>
  )
}
