import { useQuery } from '@tanstack/react-query'
import { Link, getRouteApi } from '@tanstack/react-router'
import { queries } from '@/api/queries'
import type { Box } from '@/api/schemas'
import { PageHeader } from '@/components/PageHeader'
import { PagedList } from '@/components/PagedList'
import { QueryState } from '@/components/QueryState'
import { Amounts, Fact, RecordCard, Section } from '@/components/RecordCard'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import {
  describeEggAmounts,
  formatBs,
  formatDay,
  formatInteger,
  formatPercent,
  formatRate,
  formatUsd,
} from '@/lib/format'
import { boxStatusLabels, paymentMethodLabels } from '@/lib/labels'

export function BoxCard({ box, link = true }: { box: Box; link?: boolean }) {
  return (
    <RecordCard
      title={`Caja ${box.number}`}
      subtitle={`Comprada el ${formatDay(box.purchase_day)}`}
      amount={<Badge variant={box.status === 'open' ? 'default' : 'secondary'}>{boxStatusLabels[box.status]}</Badge>}
    >
      <Fact label="Costó">{formatUsd(box.cost_usd)}</Fact>
      <Fact label="Huevos que quedan">{formatInteger(box.remaining_eggs)}</Fact>
      <Fact label="Precio de la caja">{formatUsd(box.box_price)}</Fact>
      <Fact label="Precio del cartón">{formatUsd(box.carton_price)}</Fact>
      <Fact label="Precio del medio cartón">{formatUsd(box.half_price)}</Fact>
      <Fact label="Precio del huevo suelto">{formatUsd(box.unit_price)}</Fact>
      {box.opened_on ? <Fact label="Se abrió">{formatDay(box.opened_on)}</Fact> : null}
      {box.finished_on ? <Fact label="Se terminó">{formatDay(box.finished_on)}</Fact> : null}
      {link ? (
        <div className="pt-2">
          <Link
            to="/cajas/$number"
            params={{ number: box.number }}
            className={buttonVariants({ variant: 'default', size: 'lg', className: 'w-full' })}
          >
            Ver la hoja de la caja {box.number}
          </Link>
        </div>
      ) : null}
    </RecordCard>
  )
}

const boxesRoute = getRouteApi('/app/cajas')
const boxSheetRoute = getRouteApi('/app/cajas/$number')

export function BoxesScreen() {
  const { settled: includeSettled } = boxesRoute.useSearch()
  const navigate = boxesRoute.useNavigate()
  return (
    <>
      <PageHeader title="Cajas de huevos">
        <Button
          type="button"
          variant="outline"
          size="lg"
          aria-pressed={includeSettled}
          onClick={() => void navigate({ search: { page: 1, settled: !includeSettled } })}
        >
          {includeSettled ? 'Ocultar las cajas que ya están en un cierre' : 'Mostrar también las cajas que ya están en un cierre'}
        </Button>
      </PageHeader>
      <PagedList
        options={(page) => queries.boxes(page, includeSettled)}
        empty="No hay cajas para mostrar."
        renderItem={(box) => <BoxCard key={box.number} box={box} />}
      />
    </>
  )
}

export function BoxSheetScreen() {
  const { number } = boxSheetRoute.useParams()
  const sheet = useQuery(queries.boxSheet(number))
  return (
    <>
      <PageHeader title={`Hoja de la caja ${number}`} back={{ to: '/cajas', label: 'Todas las cajas' }} />
      <QueryState query={sheet}>
        {(data) => (
          <>
            <Section title="La caja">
              <ul>
                <BoxCard box={data.box} link={false} />
              </ul>
              <dl className="mt-4 grid gap-2 rounded-xl border-2 bg-card p-4">
                <Fact label="Costo de cada huevo">{formatUsd(data.egg_cost_usd)}</Fact>
                <Fact label="Huevos vendidos">{formatInteger(data.total_eggs)}</Fact>
                <Fact label="Huevos rotos">{formatInteger(data.total_broken)}</Fact>
                <Fact label="Total vendido">{formatUsd(data.total_sales_usd)}</Fact>
              </dl>
            </Section>
            {data.profit ? (
              <Section title="Ganancia de la caja">
                <dl className="grid gap-2 rounded-xl border-2 bg-card p-4">
                  <Fact label="Costó">{formatUsd(data.profit.cost_usd)}</Fact>
                  <Fact label={`Costaría reponerla (caja ${data.profit.next_box_number})`}>
                    {formatUsd(data.profit.next_box_cost_usd)}
                  </Fact>
                  <Fact label="Diferencia">{formatUsd(data.profit.difference_usd)}</Fact>
                  <Fact label="Costo final">{formatUsd(data.profit.final_cost_usd)}</Fact>
                  <Fact label="Vendido">{formatUsd(data.profit.sales_usd)}</Fact>
                  <Fact label="Huevos rotos">
                    {formatInteger(data.profit.broken_eggs)} ({formatPercent(data.profit.broken_percent / 100)}),
                    se perdieron {formatUsd(data.profit.broken_loss_usd)}
                  </Fact>
                  <Fact label="Ganancia">
                    <span className="text-xl">{formatUsd(data.profit.profit_usd)}</span>
                  </Fact>
                </dl>
              </Section>
            ) : null}
            <Section title="Día por día">
              {data.rows.length === 0 ? (
                <p className="rounded-xl border-2 border-dashed p-6 text-lg">
                  Esta caja todavía no tiene movimiento.
                </p>
              ) : (
                <ul className="grid gap-4 md:grid-cols-2">
                  {data.rows.map((row) => (
                    <RecordCard
                      key={row.day}
                      title={formatDay(row.day)}
                      subtitle={row.rate !== null ? `Tasa ${formatRate(row.rate)}` : undefined}
                      amount={<Amounts usd={row.amount_usd} bs={row.amount_bs} />}
                    >
                      <Fact label="Se vendió">{describeEggAmounts(row)}</Fact>
                      <Fact label="Huevos">{formatInteger(row.eggs)}</Fact>
                      {row.shared_sale_eggs > 0 ? (
                        <Fact label="De ventas compartidas con otra caja">{formatInteger(row.shared_sale_eggs)}</Fact>
                      ) : null}
                      <Fact label="Rotos">{formatInteger(row.broken)}</Fact>
                      <Fact label="Otras pérdidas">{formatInteger(row.other_losses)}</Fact>
                      {row.payment_methods.length > 0 ? (
                        <Fact label="Forma de pago">
                          {row.payment_methods.map((method) => paymentMethodLabels[method]).join(', ')}
                        </Fact>
                      ) : null}
                      <Fact label="En bolívares">{formatBs(row.amount_bs)}</Fact>
                    </RecordCard>
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
