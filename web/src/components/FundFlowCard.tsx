import type { FundFlow } from '@/api/schemas'
import { Fact } from '@/components/RecordCard'
import { fundMoveKindLabels, fundMoveKinds, type Fund, fundLabels } from '@/lib/labels'
import { formatUsd } from '@/lib/format'

export function FundFlowCard({ fund, flow }: { fund: Fund; flow: FundFlow }) {
  const kinds = fundMoveKinds.filter((kind) => flow.by_kind[kind] !== undefined)
  return (
    <li className="flex flex-col gap-3 rounded-xl border-2 bg-card p-4">
      <h3 className="text-xl font-bold">{fundLabels[fund]}</h3>
      <dl className="grid gap-2">
        <Fact label="Había al empezar">{formatUsd(flow.opening_usd)}</Fact>
        <Fact label="Entró">{formatUsd(flow.entered_usd)}</Fact>
        <Fact label="Salió">{formatUsd(flow.left_usd)}</Fact>
        <Fact label="Quedó al final">
          <span className="text-xl">{formatUsd(flow.closing_usd)}</span>
        </Fact>
      </dl>
      {kinds.length > 0 ? (
        <details className="rounded-lg border p-3">
          <summary className="flex min-h-12 cursor-pointer items-center text-lg font-semibold">
            Ver de qué fue
          </summary>
          <dl className="mt-2 grid gap-2">
            {kinds.map((kind) => (
              <Fact key={kind} label={fundMoveKindLabels[kind]}>
                {formatUsd(flow.by_kind[kind] ?? 0)}
              </Fact>
            ))}
          </dl>
        </details>
      ) : null}
    </li>
  )
}
