import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { queries } from '@/api/queries'
import type { DateRange } from '@/api/client'
import { DateRangeForm } from '@/components/DateRangeForm'
import { PageHeader } from '@/components/PageHeader'
import { QueryState } from '@/components/QueryState'
import { Fact, RecordCard, Section } from '@/components/RecordCard'
import { buttonVariants } from '@/components/ui/button'
import { formatDay, formatInteger, formatQuantity, formatUsd } from '@/lib/format'
import { BoxCard } from '@/screens/Boxes'

export function StockScreen() {
  const stock = useQuery(queries.stock())
  return (
    <>
      <PageHeader title="Huevos que hay">
        <Link to="/inventario/movimiento" className={buttonVariants({ variant: 'default', size: 'lg' })}>
          Ver el movimiento de huevos por fechas
        </Link>
      </PageHeader>
      <QueryState query={stock}>
        {(data) => (
          <>
            <dl className="mb-8 grid gap-4 sm:grid-cols-2">
              <div className="rounded-xl border-2 bg-card p-4">
                <dt className="text-xl font-semibold">Huevos en total</dt>
                <dd className="text-4xl font-extrabold">{formatInteger(data.total_eggs)}</dd>
              </div>
              <div className="rounded-xl border-2 bg-card p-4">
                <dt className="text-xl font-semibold">Equivale a cajas</dt>
                <dd className="text-4xl font-extrabold">{formatQuantity(data.boxes_equivalent)}</dd>
              </div>
              {data.average_box_cost_usd !== null ? (
                <div className="rounded-xl border-2 bg-card p-4">
                  <dt className="text-lg font-semibold">Costo promedio de una caja</dt>
                  <dd className="text-2xl font-bold">{formatUsd(data.average_box_cost_usd)}</dd>
                </div>
              ) : null}
              {data.average_egg_cost_usd !== null ? (
                <div className="rounded-xl border-2 bg-card p-4">
                  <dt className="text-lg font-semibold">Costo promedio de un huevo</dt>
                  <dd className="text-2xl font-bold">{formatUsd(data.average_egg_cost_usd)}</dd>
                </div>
              ) : null}
            </dl>
            <Section title="Cajas con huevos">
              {data.boxes.length === 0 ? (
                <p className="rounded-xl border-2 border-dashed p-6 text-lg">No hay cajas con huevos.</p>
              ) : (
                <ul className="grid gap-4 md:grid-cols-2">
                  {data.boxes.map((box) => (
                    <BoxCard key={box.number} box={box} />
                  ))}
                </ul>
              )}
            </Section>
          </>
        )}
      </QueryState>
    </>
  )
}

export function LedgerScreen({
  range,
  onRange,
}: {
  range: DateRange
  onRange: (range: DateRange) => void
}) {
  const ledger = useQuery(queries.ledger(range))
  return (
    <>
      <PageHeader title="Movimiento de huevos" back={{ to: '/inventario', label: 'Huevos que hay' }} />
      <DateRangeForm key={`${range.from}|${range.to}`} value={range} onSubmit={onRange} />
      <QueryState query={ledger}>
        {(rows) =>
          rows.length === 0 ? (
            <p className="rounded-xl border-2 border-dashed p-6 text-lg">
              No hay movimiento en esas fechas.
            </p>
          ) : (
            <ul className="grid gap-4 md:grid-cols-2">
              {rows.map((row) => (
                <RecordCard key={row.day} title={formatDay(row.day)} subtitle={row.description}>
                  <Fact label="Entraron">{formatInteger(row.entered)}</Fact>
                  <Fact label="Se vendieron">{formatInteger(row.sold)}</Fact>
                  <Fact label="Rotos">{formatInteger(row.broken)}</Fact>
                  <Fact label="Otras pérdidas">{formatInteger(row.other_losses)}</Fact>
                  <Fact label="Quedaron">
                    {formatInteger(row.remaining_eggs)} huevos ({formatQuantity(row.remaining_boxes)} cajas)
                  </Fact>
                  {row.counted !== null ? (
                    <Fact label="Se contaron">
                      {formatInteger(row.counted)}
                      {row.difference !== null ? ` (diferencia ${formatInteger(row.difference)})` : ''}
                    </Fact>
                  ) : null}
                </RecordCard>
              ))}
            </ul>
          )
        }
      </QueryState>
    </>
  )
}
