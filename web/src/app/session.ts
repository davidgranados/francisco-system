import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { redirect, useRouter, type AnyRouter } from '@tanstack/react-router'
import { isUnauthorized } from '@/api/client'
import { queries } from '@/api/queries'
import type { Me } from '@/api/schemas'

const LOGIN_PATH = '/entrar'
const LAST_NAME_KEY = 'ledger.lastName'
const survivingKey = queries.people().queryKey[0]

export function lastName(): string | null {
  try {
    return localStorage.getItem(LAST_NAME_KEY)
  } catch {
    return null
  }
}

function rememberName(name: string) {
  try {
    localStorage.setItem(LAST_NAME_KEY, name)
  } catch {
    return
  }
}

export async function requireSession(queryClient: QueryClient): Promise<void> {
  try {
    await queryClient.ensureQueryData(queries.me())
  } catch (error) {
    if (isUnauthorized(error)) throw redirect({ to: LOGIN_PATH })
    throw error
  }
}

export async function signIn(queryClient: QueryClient, router: AnyRouter, me: Me, name: string) {
  rememberName(name)
  queryClient.setQueryData(queries.me().queryKey, me)
  await router.navigate({ to: '/' })
}

// Navigate first: dropping the cache while a screen still observes it leaves the login screen on "Cargando".
export async function signOut(queryClient: QueryClient, router: AnyRouter): Promise<void> {
  if (router.state.location.pathname === LOGIN_PATH) return
  await router.navigate({ to: LOGIN_PATH })
  queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== survivingKey })
}

export function signOutIfUnauthorized(error: unknown, queryClient: QueryClient, router: AnyRouter) {
  if (isUnauthorized(error)) void signOut(queryClient, router)
}

export function useSession() {
  const queryClient = useQueryClient()
  const router = useRouter()
  return {
    signIn: (me: Me, name: string) => signIn(queryClient, router, me, name),
    signOut: () => signOut(queryClient, router),
  }
}
