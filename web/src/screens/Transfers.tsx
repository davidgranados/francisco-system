import { queries } from '@/api/queries'
import type { Transfer } from '@/api/schemas'
import { PageHeader } from '@/components/PageHeader'
import { PagedList } from '@/components/PagedList'
import { Amounts, Fact, RecordCard } from '@/components/RecordCard'
import { formatDay } from '@/lib/format'
import { fundLabels, transferKindLabels } from '@/lib/labels'

function route(transfer: Transfer): string {
  const origin = fundLabels[transfer.from_fund]
  if (transfer.to_fund) return `De ${origin} a ${fundLabels[transfer.to_fund]}`
  if (transfer.partner) return `De ${origin} a ${transfer.partner}`
  return `Sale de ${origin}`
}

export function TransfersScreen() {
  return (
    <>
      <PageHeader title="Movimientos de dinero" />
      <PagedList
        options={queries.transfers}
        empty="Todavía no hay movimientos de dinero."
        renderItem={(transfer) => (
          <RecordCard
            key={transfer.id}
            title={transferKindLabels[transfer.kind]}
            subtitle={formatDay(transfer.day)}
            amount={<Amounts usd={transfer.amount_usd} voided={transfer.voided} />}
            voided={transfer.voided}
            voidReason={transfer.void_reason}
          >
            <Fact label="Camino del dinero">{route(transfer)}</Fact>
            {transfer.note ? <Fact label="Nota">{transfer.note}</Fact> : null}
          </RecordCard>
        )}
      />
    </>
  )
}
