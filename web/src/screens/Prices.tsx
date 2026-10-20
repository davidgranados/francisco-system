import { useQuery } from '@tanstack/react-query'
import { queries } from '@/api/queries'
import { PageHeader } from '@/components/PageHeader'
import { QueryState } from '@/components/QueryState'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { formatBs, formatDay, formatRate, formatUsd } from '@/lib/format'

export function PricesScreen() {
  const prices = useQuery(queries.prices())
  return (
    <>
      <PageHeader title="Precios de hoy" />
      <QueryState query={prices}>
        {(data) => {
          const lines = [
            { label: 'Caja completa (360 huevos)', price: data.box },
            { label: 'Cartón (30 huevos)', price: data.carton },
            { label: 'Medio cartón (15 huevos)', price: data.half },
            { label: 'Huevo suelto', price: data.unit },
          ]
          return (
            <>
              <p className="mb-4 text-xl">
                {formatDay(data.day)}, caja {data.box_number}. Tasa: <strong>{formatRate(data.rate)}</strong>
              </p>
              {data.rate_stale ? (
                <Alert className="mb-4">
                  <AlertDescription>
                    Hoy todavía no hay tasa. Se usó la última que se tiene.
                  </AlertDescription>
                </Alert>
              ) : null}
              {data.notice ? (
                <Alert className="mb-4">
                  <AlertDescription>{data.notice}</AlertDescription>
                </Alert>
              ) : null}
              <dl className="grid gap-4 sm:grid-cols-2">
                {lines.map((line) => (
                  <div key={line.label} className="rounded-xl border-2 bg-card p-4">
                    <dt className="text-lg font-semibold">{line.label}</dt>
                    <dd className="text-3xl font-extrabold">{formatUsd(line.price.usd)}</dd>
                    <dd className="text-xl text-muted-foreground">{formatBs(line.price.bs)}</dd>
                  </div>
                ))}
              </dl>
            </>
          )
        }}
      </QueryState>
    </>
  )
}
