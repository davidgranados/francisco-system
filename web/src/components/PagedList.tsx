import { useQuery, type QueryKey, type UseQueryOptions } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import type { Page } from '@/api/schemas'
import { Pager } from '@/components/Pager'
import { QueryState } from '@/components/QueryState'

export function PagedList<T, Key extends QueryKey>({
  options,
  empty,
  renderItem,
}: {
  options: (page: number) => UseQueryOptions<Page<T>, Error, Page<T>, Key>
  empty: string
  renderItem: (item: T) => ReactNode
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
            <ul className="grid gap-4 md:grid-cols-2">{data.items.map(renderItem)}</ul>
          )}
          {data.total > data.page_size || page > 1 ? (
            <Pager page={page} total={data.total} pageSize={data.page_size} onPage={onPage} />
          ) : null}
        </>
      )}
    </QueryState>
  )
}
