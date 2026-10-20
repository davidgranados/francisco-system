import { Link } from '@tanstack/react-router'
import { queries } from '@/api/queries'
import { PageHeader } from '@/components/PageHeader'
import { PagedList } from '@/components/PagedList'
import { Amounts, Fact, RecordCard } from '@/components/RecordCard'
import { formatDay, formatRate, formatUsd, pluralize } from '@/lib/format'
import { boxStatusLabels, paymentMethodLabels } from '@/lib/labels'

export function PurchasesScreen({ page, onPage }: { page: number; onPage: (page: number) => void }) {
  return (
    <>
      <PageHeader title="Compras" />
      <PagedList
        options={queries.purchases(page)}
        page={page}
        onPage={onPage}
        empty="Todavía no hay compras."
        renderItem={(purchase) => (
          <RecordCard
            key={purchase.id}
            title={formatDay(purchase.day)}
            subtitle={purchase.supplier ?? undefined}
            amount={
              <Amounts usd={purchase.total_usd} bs={purchase.total_bs} voided={purchase.voided} />
            }
            voided={purchase.voided}
            voidReason={purchase.void_reason}
          >
            <Fact label="Cajas compradas">
              {pluralize(purchase.box_count, 'caja', 'cajas')} a {formatUsd(purchase.cost_per_box_usd)}
            </Fact>
            <Fact label="Forma de pago">{paymentMethodLabels[purchase.payment_method]}</Fact>
            <Fact label="Tasa del día">{formatRate(purchase.rate)}</Fact>
            {purchase.boxes.length > 0 ? (
              <Fact label="Cajas">
                <ul className="flex flex-col items-end gap-1">
                  {purchase.boxes.map((box) => (
                    <li key={box.number}>
                      <Link
                        to="/cajas/$number"
                        params={{ number: box.number }}
                        className="inline-flex min-h-12 items-center text-primary underline"
                      >
                        Caja {box.number} ({boxStatusLabels[box.status]})
                      </Link>
                    </li>
                  ))}
                </ul>
              </Fact>
            ) : null}
            {purchase.note ? <Fact label="Nota">{purchase.note}</Fact> : null}
          </RecordCard>
        )}
      />
    </>
  )
}
