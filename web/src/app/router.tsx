import { QueryCache, QueryClient, type QueryClientConfig } from '@tanstack/react-query'
import {
  Link,
  Outlet,
  createRootRouteWithContext,
  createRoute,
  createRouter,
  redirect,
  useNavigate,
  useSearch,
  type ErrorComponentProps,
  type RouterHistory,
} from '@tanstack/react-router'
import type { ComponentType } from 'react'
import { z } from 'zod'
import { isUnauthorized } from '@/api/client'
import { queries } from '@/api/queries'
import { signOut } from '@/app/session'
import { AppShell } from '@/components/AppShell'
import { ErrorNotice } from '@/components/QueryState'
import { buttonVariants } from '@/components/ui/button'
import { startOfMonth, today } from '@/lib/format'
import { BoxSheetScreen, BoxesScreen } from '@/screens/Boxes'
import { ContributionsScreen } from '@/screens/Contributions'
import { ExpensesScreen, PendingExpensesScreen } from '@/screens/Expenses'
import { HomeScreen } from '@/screens/Home'
import { LedgerScreen, StockScreen } from '@/screens/Inventory'
import { LoginScreen } from '@/screens/Login'
import { MoneyScreen, SummaryScreen } from '@/screens/Money'
import { PartnersScreen } from '@/screens/Partners'
import { PricesScreen } from '@/screens/Prices'
import { PurchasesScreen } from '@/screens/Purchases'
import { RatesScreen } from '@/screens/Rates'
import { SalesScreen } from '@/screens/Sales'
import { SettlementsScreen } from '@/screens/Settlements'
import { TransfersScreen } from '@/screens/Transfers'

interface RouterContext {
  queryClient: QueryClient
}

const pageSearch = z.object({ page: z.coerce.number().int().min(1).catch(1) })
const dayParam = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/)
  .optional()
  .catch(undefined)
const rangeSearch = z.object({ from: dayParam, to: dayParam })

function RouteError({ error, reset }: ErrorComponentProps) {
  return (
    <main className="mx-auto max-w-xl space-y-4 px-4 py-10">
      <ErrorNotice
        message={error instanceof Error ? error.message : 'Algo salió mal. Intente otra vez.'}
        onRetry={reset}
      />
      <Link to="/" className={buttonVariants({ variant: 'outline', size: 'lg' })}>
        Ir al inicio
      </Link>
    </main>
  )
}

function NotFound() {
  return (
    <main className="mx-auto max-w-xl space-y-4 px-4 py-10">
      <h1 className="text-3xl font-extrabold">Esa página no existe</h1>
      <Link to="/" className={buttonVariants({ size: 'lg' })}>
        Ir al inicio
      </Link>
    </main>
  )
}

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: Outlet,
  errorComponent: RouteError,
  notFoundComponent: NotFound,
})

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/entrar',
  component: LoginScreen,
})

const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'app',
  beforeLoad: async ({ context }) => {
    try {
      await context.queryClient.ensureQueryData(queries.me())
    } catch (error) {
      if (isUnauthorized(error)) throw redirect({ to: '/entrar' })
      throw error
    }
  },
  component: AppShell,
})

const homeRoute = createRoute({ getParentRoute: () => appRoute, path: '/', component: HomeScreen })

const salesRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/ventas',
  validateSearch: pageSearch.extend({ day: dayParam }),
  component: function Sales() {
    const { page, day } = salesRoute.useSearch()
    const navigate = salesRoute.useNavigate()
    return (
      <SalesScreen
        page={page}
        day={day}
        onPage={(next) => void navigate({ search: (previous) => ({ ...previous, page: next }) })}
        onDay={(next) => void navigate({ search: { page: 1, day: next } })}
      />
    )
  },
})

interface PagedProps {
  page: number
  onPage: (page: number) => void
}

function PagedScreen({ Screen }: { Screen: ComponentType<PagedProps> }) {
  const search: { page?: number } = useSearch({ strict: false })
  const navigate = useNavigate()
  return (
    <Screen
      page={search.page ?? 1}
      onPage={(next) => void navigate({ to: '.', search: (previous) => ({ ...previous, page: next }) })}
    />
  )
}

function pagedRoute<Path extends string>(path: Path, Screen: ComponentType<PagedProps>) {
  return createRoute({
    getParentRoute: () => appRoute,
    path,
    validateSearch: pageSearch,
    component: () => <PagedScreen Screen={Screen} />,
  })
}

const purchasesRoute = pagedRoute('/compras', PurchasesScreen)
const expensesRoute = pagedRoute('/gastos', ExpensesScreen)
const contributionsRoute = pagedRoute('/aportes', ContributionsScreen)
const transfersRoute = pagedRoute('/movimientos', TransfersScreen)
const settlementsRoute = pagedRoute('/cierres', SettlementsScreen)
const ratesRoute = pagedRoute('/tasas', RatesScreen)

const pendingExpensesRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/gastos/pendientes',
  component: PendingExpensesScreen,
})

const boxesRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/cajas',
  validateSearch: pageSearch.extend({ settled: z.boolean().catch(false) }),
  component: function Boxes() {
    const { page, settled } = boxesRoute.useSearch()
    const navigate = boxesRoute.useNavigate()
    return (
      <BoxesScreen
        page={page}
        includeSettled={settled}
        onPage={(next) => void navigate({ search: (previous) => ({ ...previous, page: next }) })}
        onIncludeSettled={(value) => void navigate({ search: { page: 1, settled: value } })}
      />
    )
  },
})

const boxSheetRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/cajas/$number',
  params: {
    parse: (params) => ({ number: z.coerce.number().int().positive().parse(params.number) }),
    stringify: (params) => ({ number: String(params.number) }),
  },
  component: function BoxSheet() {
    const { number } = boxSheetRoute.useParams()
    return <BoxSheetScreen number={number} />
  },
})

const stockRoute = createRoute({ getParentRoute: () => appRoute, path: '/inventario', component: StockScreen })

function withDefaultRange(search: { from?: string | undefined; to?: string | undefined }) {
  return { from: search.from ?? startOfMonth(), to: search.to ?? today() }
}

const ledgerRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/inventario/movimiento',
  validateSearch: rangeSearch,
  component: function Ledger() {
    const range = withDefaultRange(ledgerRoute.useSearch())
    const navigate = ledgerRoute.useNavigate()
    return <LedgerScreen range={range} onRange={(next) => void navigate({ search: next })} />
  },
})

const moneyRoute = createRoute({ getParentRoute: () => appRoute, path: '/dinero', component: MoneyScreen })

const summaryRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/dinero/resumen',
  validateSearch: rangeSearch,
  component: function Summary() {
    const range = withDefaultRange(summaryRoute.useSearch())
    const navigate = summaryRoute.useNavigate()
    return <SummaryScreen range={range} onRange={(next) => void navigate({ search: next })} />
  },
})

const pricesRoute = createRoute({ getParentRoute: () => appRoute, path: '/precios', component: PricesScreen })
const partnersRoute = createRoute({ getParentRoute: () => appRoute, path: '/socios', component: PartnersScreen })

const routeTree = rootRoute.addChildren([
  loginRoute,
  appRoute.addChildren([
    homeRoute,
    salesRoute,
    purchasesRoute,
    expensesRoute,
    pendingExpensesRoute,
    contributionsRoute,
    transfersRoute,
    settlementsRoute,
    boxesRoute,
    boxSheetRoute,
    stockRoute,
    ledgerRoute,
    moneyRoute,
    summaryRoute,
    pricesRoute,
    ratesRoute,
    partnersRoute,
  ]),
])

export function createAppRouter(options: { history?: RouterHistory; queryConfig?: QueryClientConfig } = {}) {
  const queryClient: QueryClient = new QueryClient({
    ...options.queryConfig,
    queryCache: new QueryCache({
      onError: (error) => {
        if (isUnauthorized(error)) {
          void signOut(queryClient, router)
        }
      },
    }),
    defaultOptions: { queries: { retry: false, staleTime: 30_000, refetchOnWindowFocus: false } },
  })
  const router = createRouter({
    routeTree,
    context: { queryClient },
    history: options.history,
    defaultPreload: false,
  })
  return { router, queryClient }
}

export type AppRouter = ReturnType<typeof createAppRouter>['router']

declare module '@tanstack/react-router' {
  interface Register {
    router: AppRouter
  }
}
