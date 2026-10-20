import { PageHeader } from '@/components/PageHeader'
import { PagedList } from '@/components/PagedList'
import { Amounts, Fact, RecordCard } from '@/components/RecordCard'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { queries } from '@/api/queries'
import { describeEggAmounts, formatDay, formatInteger, formatRate } from '@/lib/format'
import { paymentMethodLabels } from '@/lib/labels'

export function SalesScreen({
  page,
  day,
  onPage,
  onDay,
}: {
  page: number
  day?: string
  onPage: (page: number) => void
  onDay: (day: string | undefined) => void
}) {
  return (
    <>
      <PageHeader title="Ventas" />
      <div className="mb-6 flex flex-wrap items-end gap-3 rounded-xl border-2 bg-card p-4">
        <div className="space-y-2">
          <Label htmlFor="sales-day">Ver solo un día</Label>
          <Input
            id="sales-day"
            type="date"
            value={day ?? ''}
            onChange={(event) => onDay(event.target.value || undefined)}
          />
        </div>
        {day ? (
          <Button type="button" variant="outline" size="lg" onClick={() => onDay(undefined)}>
            Ver todos los días
          </Button>
        ) : null}
      </div>
      <PagedList
        options={queries.sales(page, day)}
        page={page}
        onPage={onPage}
        empty={day ? `No hay ventas el ${formatDay(day)}.` : 'Todavía no hay ventas.'}
        renderItem={(sale) => (
          <RecordCard
            key={sale.id}
            title={formatDay(sale.day)}
            subtitle={sale.customer ?? undefined}
            amount={<Amounts usd={sale.amount_usd} bs={sale.amount_bs} voided={sale.voided} />}
            voided={sale.voided}
            voidReason={sale.void_reason}
          >
            <Fact label="Se vendió">{describeEggAmounts(sale)}</Fact>
            <Fact label="Huevos en total">{formatInteger(sale.eggs)}</Fact>
            <Fact label="Forma de pago">{paymentMethodLabels[sale.payment_method]}</Fact>
            <Fact label="Tasa del día">{formatRate(sale.rate)}</Fact>
            {sale.parts.length > 0 ? (
              <Fact label="Salió de">
                {sale.parts
                  .map((part) => `caja ${part.box_number} (${formatInteger(part.eggs)} huevos)`)
                  .join(', ')}
              </Fact>
            ) : null}
            {sale.note ? <Fact label="Nota">{sale.note}</Fact> : null}
          </RecordCard>
        )}
      />
    </>
  )
}
