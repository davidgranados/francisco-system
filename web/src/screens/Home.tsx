import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { queries } from '@/api/queries'
import { PageHeader } from '@/components/PageHeader'
import { ErrorNotice, LoadingNotice } from '@/components/QueryState'
import { formatUsd } from '@/lib/format'

const sections = [
  { to: '/ventas', title: 'Ventas', hint: 'Lo que se ha vendido' },
  { to: '/compras', title: 'Compras', hint: 'Las cajas que se compraron' },
  { to: '/gastos', title: 'Gastos', hint: 'Lo que se pagó y lo que falta devolver' },
  { to: '/cajas', title: 'Cajas de huevos', hint: 'Cada caja y su hoja de cuentas' },
  { to: '/inventario', title: 'Huevos que hay', hint: 'Existencia y movimiento por fechas' },
  { to: '/cierres', title: 'Cierres', hint: 'Cada cierre y el reparto a los socios' },
  { to: '/aportes', title: 'Aportes', hint: 'El dinero que pusieron los socios' },
  { to: '/movimientos', title: 'Movimientos de dinero', hint: 'Traspasos, devoluciones y retiros' },
  { to: '/dinero', title: 'Dinero', hint: 'Cómo se movió cada fondo y resumen por fechas' },
  { to: '/precios', title: 'Precios de hoy', hint: 'Caja, cartón, medio cartón y huevo' },
  { to: '/tasas', title: 'Tasa del dólar', hint: 'La tasa de cada día' },
  { to: '/socios', title: 'Socios', hint: 'Quiénes son y cuánto les toca' },
] as const

export function HomeScreen() {
  const balances = useQuery(queries.balances())
  return (
    <>
      <PageHeader title="Inicio" />
      <section aria-labelledby="balances-title" className="mb-8">
        <h2 id="balances-title" className="mb-3 text-2xl font-bold">
          El dinero que hay hoy
        </h2>
        {balances.isPending ? <LoadingNotice /> : null}
        {balances.isError ? (
          <ErrorNotice message={balances.error.message} onRetry={() => void balances.refetch()} />
        ) : null}
        {balances.data ? (
          <dl className="grid gap-4 sm:grid-cols-3">
            {[
              { label: 'Capital', value: balances.data.capital_usd },
              { label: 'Caja chica', value: balances.data.petty_cash_usd },
              { label: 'Ahorros', value: balances.data.savings_usd },
            ].map((fund) => (
              <div key={fund.label} className="rounded-xl border-2 bg-card p-4">
                <dt className="text-xl font-semibold">{fund.label}</dt>
                <dd className="text-4xl font-extrabold">{formatUsd(fund.value)}</dd>
              </div>
            ))}
          </dl>
        ) : null}
      </section>
      <nav aria-label="Secciones">
        <ul className="grid gap-4 sm:grid-cols-2">
          {sections.map((section) => (
            <li key={section.to}>
              <Link
                to={section.to}
                className="flex min-h-28 flex-col justify-center gap-1 rounded-xl border-2 bg-card p-5 hover:bg-muted"
              >
                <span className="text-2xl font-bold text-primary">{section.title}</span>
                <span className="text-base text-muted-foreground">{section.hint}</span>
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </>
  )
}
