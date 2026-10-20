import { queries } from '@/api/queries'
import { PageHeader } from '@/components/PageHeader'
import { PagedList } from '@/components/PagedList'
import { Fact, RecordCard } from '@/components/RecordCard'
import { formatDay, formatRate } from '@/lib/format'
import { rateSourceLabels } from '@/lib/labels'

export function RatesScreen({ page, onPage }: { page: number; onPage: (page: number) => void }) {
  return (
    <>
      <PageHeader title="Tasa del dólar" />
      <PagedList
        options={queries.rates(page)}
        page={page}
        onPage={onPage}
        empty="Todavía no hay tasas guardadas."
        renderItem={(rate) => (
          <RecordCard
            key={rate.day}
            title={formatDay(rate.day)}
            amount={<p className="text-2xl font-bold">{formatRate(rate.rate)}</p>}
          >
            <Fact label="De dónde salió">{rateSourceLabels[rate.source]}</Fact>
          </RecordCard>
        )}
      />
    </>
  )
}
