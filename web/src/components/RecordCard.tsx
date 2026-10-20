import type { ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'
import { formatBs, formatUsd } from '@/lib/format'
import { cn } from '@/lib/utils'

export function Amounts({ usd, bs, voided }: { usd: number; bs?: number; voided?: boolean }) {
  return (
    <p className={cn('text-right', voided && 'line-through')}>
      <span className="block text-2xl font-bold">{formatUsd(usd)}</span>
      {bs !== undefined ? <span className="block text-base text-muted-foreground">{formatBs(bs)}</span> : null}
    </p>
  )
}

export function RecordCard({
  title,
  subtitle,
  amount,
  voided = false,
  voidReason,
  children,
}: {
  title: string
  subtitle?: string
  amount?: ReactNode
  voided?: boolean
  voidReason?: string | null
  children?: ReactNode
}) {
  return (
    <li
      className={cn(
        'flex flex-col gap-3 rounded-xl border-2 bg-card p-4',
        voided && 'border-destructive bg-muted',
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-xl font-bold break-words">{title}</h2>
          {subtitle ? <p className="text-base text-muted-foreground">{subtitle}</p> : null}
        </div>
        {amount}
      </div>
      {voided ? (
        <div>
          <Badge variant="destructive" className="border-destructive">
            Anulada
          </Badge>
          {voidReason ? <p className="mt-1 text-base">Motivo: {voidReason}</p> : null}
        </div>
      ) : null}
      {children ? <dl className="grid gap-2">{children}</dl> : null}
    </li>
  )
}

export function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap justify-between gap-x-4 border-t pt-2 first:border-t-0 first:pt-0">
      <dt className="text-base text-muted-foreground">{label}</dt>
      <dd className="text-base font-semibold break-words">{children}</dd>
    </div>
  )
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-8 first:mt-0">
      <h2 className="mb-3 text-2xl font-bold">{title}</h2>
      {children}
    </section>
  )
}
