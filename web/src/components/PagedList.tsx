import { useQuery, type QueryKey, type UseQueryOptions } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import type { Page } from '@/api/schemas'
import { Pager } from '@/components/Pager'
import { QueryState } from '@/components/QueryState'

export function PagedList<T, Key extends QueryKey>({
  options,
  page,
  onPage,
  empty,
  renderItem,
}: {
  options: UseQueryOptions<Page<T>, Error, Page<T>, Key>
  page: number
  onPage: (page: number) => void
  empty: string
  renderItem: (item: T) => ReactNode
}) {
  const query = useQuery(options)
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
