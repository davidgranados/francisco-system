import { useQuery, type QueryKey, type UseQueryOptions } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import type { Page } from '@/api/schemas'
import { Pager } from '@/components/Pager'
import { QueryState } from '@/components/QueryState'

export function PagedList<P extends Page<unknown>, Key extends QueryKey>({
  options,
  empty,
  summary,
  renderItem,
}: {
  options: (page: number) => UseQueryOptions<P, Error, P, Key>
  empty: string
  summary?: (data: P) => ReactNode
  renderItem: (item: P['items'][number]) => ReactNode
}) {
  const { page = 1 }: { page?: number } = useSearch({ strict: false })
  const navigate = useNavigate()
  const query = useQuery(options(page))
  const onPage = (next: number) =>
    void navigate({ to: '.', search: (previous) => ({ ...previous, page: next }) })
  return (
    <QueryState query={query}>
      {(data) => (
        <>
          {data.items.length === 0 ? (
            <p className="rounded-xl border-2 border-dashed p-6 text-lg">{empty}</p>
          ) : (
            <>
              {summary?.(data)}
              <ul className="grid gap-4 md:grid-cols-2">{data.items.map(renderItem)}</ul>
            </>
          )}
          {data.total > data.page_size || page > 1 ? (
            <Pager page={page} total={data.total} pageSize={data.page_size} onPage={onPage} />
          ) : null}
        </>
      )}
    </QueryState>
  )
}
