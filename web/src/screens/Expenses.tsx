import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { queries } from '@/api/queries'
import type { Expense } from '@/api/schemas'
import { PageHeader } from '@/components/PageHeader'
import { PagedList } from '@/components/PagedList'
import { QueryState } from '@/components/QueryState'
import { Amounts, Fact, RecordCard } from '@/components/RecordCard'
import { Badge } from '@/components/ui/badge'
import { buttonVariants } from '@/components/ui/button'
import { formatDay, formatRate, formatUsd } from '@/lib/format'

function ExpenseCard({ expense }: { expense: Expense }) {
  const owedToPartner = expense.paid_by_partner !== null && expense.reimbursed_on === null
  return (
    <RecordCard
      title={expense.concept}
      subtitle={formatDay(expense.day)}
      amount={<Amounts usd={expense.amount_usd} bs={expense.amount_bs} />}
    >
      <Fact label="Lo pagó">{expense.paid_by_partner ?? 'El negocio'}</Fact>
      {expense.paid_by_partner !== null ? (
        <Fact label="Devolución">
          {owedToPartner ? (
            <Badge variant="destructive" className="border-destructive">
              Falta devolver
            </Badge>
          ) : (
            `Devuelto el ${formatDay(expense.reimbursed_on ?? expense.day)}`
          )}
        </Fact>
      ) : null}
      <Fact label="Tasa del día">{formatRate(expense.rate)}</Fact>
      <Fact label="Cierre">{expense.settled ? 'Ya entró en un cierre' : 'Todavía no entra en un cierre'}</Fact>
    </RecordCard>
  )
}

export function ExpensesScreen({ page, onPage }: { page: number; onPage: (page: number) => void }) {
  return (
    <>
      <PageHeader title="Gastos">
        <Link to="/gastos/pendientes" className={buttonVariants({ variant: 'default', size: 'lg' })}>
          Ver lo que falta devolver a los socios
        </Link>
      </PageHeader>
      <PagedList
        options={queries.expenses(page)}
        page={page}
        onPage={onPage}
        empty="Todavía no hay gastos."
        renderItem={(expense) => <ExpenseCard key={expense.id} expense={expense} />}
      />
    </>
  )
}

export function PendingExpensesScreen() {
  const pending = useQuery(queries.pendingExpenses())
  return (
    <>
      <PageHeader title="Falta devolver a los socios" back={{ to: '/gastos', label: 'Todos los gastos' }} />
      <QueryState query={pending}>
        {(expenses) => {
          const total = expenses.reduce((sum, expense) => sum + expense.amount_usd, 0)
          return expenses.length === 0 ? (
            <p className="rounded-xl border-2 border-dashed p-6 text-lg">
              No se le debe nada a ningún socio.
            </p>
          ) : (
            <>
              <p className="mb-4 rounded-xl border-2 bg-card p-4 text-xl">
                En total se les debe <strong>{formatUsd(total)}</strong>
              </p>
              <ul className="grid gap-4 md:grid-cols-2">
                {expenses.map((expense) => (
                  <ExpenseCard key={expense.id} expense={expense} />
                ))}
              </ul>
            </>
          )
        }}
      </QueryState>
    </>
  )
}
