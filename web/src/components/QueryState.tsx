import type { UseQueryResult } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

export function LoadingNotice() {
  return (
    <div role="status" className="space-y-3" aria-live="polite">
      <p className="text-lg font-semibold">Cargando, un momento…</p>
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  )
}

export function ErrorNotice({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Alert variant="destructive">
      <AlertTitle className="text-lg font-bold">No se pudo mostrar esta pantalla</AlertTitle>
      <AlertDescription>
        <p>{message}</p>
        {onRetry ? (
          <Button type="button" variant="outline" className="mt-3" onClick={onRetry}>
            Intentar de nuevo
          </Button>
        ) : null}
      </AlertDescription>
    </Alert>
  )
}

export function QueryState<T>({
  query,
  children,
}: {
  query: UseQueryResult<T, Error>
  children: (data: T) => ReactNode
}) {
  if (query.isPending) return <LoadingNotice />
  if (query.isError)
    return <ErrorNotice message={query.error.message} onRetry={() => void query.refetch()} />
  return (
    <div aria-busy={query.isPlaceholderData} className={query.isPlaceholderData ? 'opacity-60' : undefined}>
      {children(query.data)}
    </div>
  )
}
