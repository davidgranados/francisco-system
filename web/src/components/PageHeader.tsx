import { Link } from '@tanstack/react-router'
import { useEffect, type ReactNode } from 'react'
import { buttonVariants } from '@/components/ui/button'

export function PageHeader({
  title,
  back,
  children,
}: {
  title: string
  back?: { to: string; label: string }
  children?: ReactNode
}) {
  useEffect(() => {
    document.title = `${title} · Cuentas de los huevos`
  }, [title])
  return (
    <header className="mb-6 space-y-3">
      {back ? (
        <Link to={back.to} className={buttonVariants({ variant: 'outline' })}>
          ← {back.label}
        </Link>
      ) : null}
      <h1 className="text-3xl font-extrabold">{title}</h1>
      {children}
    </header>
  )
}
