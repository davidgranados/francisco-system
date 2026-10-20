import { useQuery } from '@tanstack/react-query'
import { queries } from '@/api/queries'
import { PageHeader } from '@/components/PageHeader'
import { QueryState } from '@/components/QueryState'
import { Fact, RecordCard } from '@/components/RecordCard'
import { Badge } from '@/components/ui/badge'
import { formatPercent } from '@/lib/format'

export function PartnersScreen() {
  const partners = useQuery(queries.partners())
  return (
    <>
      <PageHeader title="Socios" />
      <QueryState query={partners}>
        {(data) =>
          data.length === 0 ? (
            <p className="rounded-xl border-2 border-dashed p-6 text-lg">No hay socios anotados.</p>
          ) : (
            <ul className="grid gap-4 md:grid-cols-2">
              {data.map((partner) => (
                <RecordCard
                  key={partner.name}
                  title={partner.name}
                  amount={
                    <Badge variant={partner.active ? 'default' : 'secondary'}>
                      {partner.active ? 'Activo' : 'Ya no es socio activo'}
                    </Badge>
                  }
                >
                  <Fact label="Le toca">{formatPercent(partner.share)} de las ganancias</Fact>
                </RecordCard>
              ))}
            </ul>
          )
        }
      </QueryState>
    </>
  )
}
