import { queries } from '@/api/queries'
import { PageHeader } from '@/components/PageHeader'
import { PagedList } from '@/components/PagedList'
import { Amounts, Fact, RecordCard } from '@/components/RecordCard'
import { formatDay } from '@/lib/format'

export function ContributionsScreen() {
  return (
    <>
      <PageHeader title="Aportes" />
      <PagedList
        options={queries.contributions}
        empty="Todavía no hay aportes."
        renderItem={(contribution) => (
          <RecordCard
            key={contribution.id}
            title={contribution.partner}
            subtitle={formatDay(contribution.day)}
            amount={<Amounts usd={contribution.amount_usd} />}
          >
            {contribution.note ? <Fact label="Nota">{contribution.note}</Fact> : null}
          </RecordCard>
        )}
      />
    </>
  )
}
