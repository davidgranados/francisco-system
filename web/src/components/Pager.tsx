import { Button } from '@/components/ui/button'
import { formatInteger } from '@/lib/format'

export function pageCount(total: number, pageSize: number): number {
  return Math.max(1, Math.ceil(total / pageSize))
}

export function Pager({
  page,
  total,
  pageSize,
  onPage,
}: {
  page: number
  total: number
  pageSize: number
  onPage: (page: number) => void
}) {
  const pages = pageCount(total, pageSize)
  return (
    <nav aria-label="Páginas" className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <Button type="button" size="lg" variant="outline" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Anterior
      </Button>
      <p className="text-center text-lg font-semibold" aria-live="polite">
        Página {page} de {pages}
        <span className="block text-base font-normal text-muted-foreground">
          {formatInteger(total)} en total
        </span>
      </p>
      <Button type="button" size="lg" variant="outline" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Siguiente
      </Button>
    </nav>
  )
}
