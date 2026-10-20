import { Link } from '@tanstack/react-router'
import { queries } from '@/api/queries'
import type { Expense } from '@/api/schemas'
import { PageHeader } from '@/components/PageHeader'
import { PagedList } from '@/components/PagedList'
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

export function ExpensesScreen() {
  return (
    <>
      <PageHeader title="Gastos">
        <Link to="/gastos/pendientes" className={buttonVariants({ variant: 'default', size: 'lg' })}>
          Ver lo que falta devolver a los socios
        </Link>
      </PageHeader>
      <PagedList
        options={queries.expenses}
        empty="Todavía no hay gastos."
        renderItem={(expense) => <ExpenseCard key={expense.id} expense={expense} />}
      />
    </>
  )
}

export function PendingExpensesScreen() {
  return (
    <>
      <PageHeader title="Falta devolver a los socios" back={{ to: '/gastos', label: 'Todos los gastos' }} />
      <PagedList
        options={queries.owedExpenses}
        empty="No se le debe nada a ningún socio."
        summary={(data) => (
          <p className="mb-4 rounded-xl border-2 bg-card p-4 text-xl">
            En total se les debe <strong>{formatUsd(data.owed_usd)}</strong>
          </p>
        )}
        renderItem={(expense) => <ExpenseCard key={expense.id} expense={expense} />}
      />
    </>
  )
}
