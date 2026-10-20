import { QueryCache, QueryClient, type QueryClientConfig } from '@tanstack/react-query'
import {
  Link,
  Outlet,
  createRootRouteWithContext,
  createRoute,
  createRouter,
  type ErrorComponentProps,
  type RouterHistory,
} from '@tanstack/react-router'
import { z } from 'zod'
import { requireSession, signOutIfUnauthorized } from '@/app/session'
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
const dayFormat = z.string().regex(/^\d{4}-\d{2}-\d{2}$/)
const dayParam = dayFormat.optional().catch(undefined)
const rangeSearch = z.object({
  from: dayFormat.default(startOfMonth).catch(startOfMonth),
  to: dayFormat.default(today).catch(today),
})

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
  beforeLoad: ({ context }) => requireSession(context.queryClient),
  component: AppShell,
})

const homeRoute = createRoute({ getParentRoute: () => appRoute, path: '/', component: HomeScreen })

const salesRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/ventas',
  validateSearch: pageSearch.extend({ day: dayParam }),
  component: SalesScreen,
})

const purchasesRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/compras',
  validateSearch: pageSearch,
  component: PurchasesScreen,
})

const expensesRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/gastos',
  validateSearch: pageSearch,
  component: ExpensesScreen,
})

const pendingExpensesRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/gastos/pendientes',
  component: PendingExpensesScreen,
})

const contributionsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/aportes',
  validateSearch: pageSearch,
  component: ContributionsScreen,
})

const transfersRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/movimientos',
  validateSearch: pageSearch,
  component: TransfersScreen,
})

const settlementsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/cierres',
  validateSearch: pageSearch,
  component: SettlementsScreen,
})

const ratesRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/tasas',
  validateSearch: pageSearch,
  component: RatesScreen,
})

const boxesRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/cajas',
  validateSearch: pageSearch.extend({ settled: z.boolean().catch(false) }),
  component: BoxesScreen,
})

const boxSheetRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/cajas/$number',
  params: {
    parse: (params) => ({ number: z.coerce.number().int().positive().parse(params.number) }),
    stringify: (params) => ({ number: String(params.number) }),
  },
  component: BoxSheetScreen,
})

const stockRoute = createRoute({ getParentRoute: () => appRoute, path: '/inventario', component: StockScreen })

const ledgerRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/inventario/movimiento',
  validateSearch: rangeSearch,
  component: LedgerScreen,
})

const moneyRoute = createRoute({ getParentRoute: () => appRoute, path: '/dinero', component: MoneyScreen })

const summaryRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/dinero/resumen',
  validateSearch: rangeSearch,
  component: SummaryScreen,
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
      onError: (error) => signOutIfUnauthorized(error, queryClient, router),
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
