import type { QueryClient } from '@tanstack/react-query'
import type { AnyRouter } from '@tanstack/react-router'
import { queries } from '@/api/queries'

const LOGIN_PATH = '/entrar'
const loginQueryKey = queries.people().queryKey[0]

export async function signOut(queryClient: QueryClient, router: AnyRouter): Promise<void> {
  if (router.state.location.pathname === LOGIN_PATH) return
  await router.navigate({ to: LOGIN_PATH })
  queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== loginQueryKey })
}
