import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, Outlet, useRouter, useRouterState } from '@tanstack/react-router'
import { useEffect, useRef } from 'react'
import { api } from '@/api/client'
import { queries } from '@/api/queries'
import { signOut } from '@/app/session'
import { Button, buttonVariants } from '@/components/ui/button'

export function AppShell() {
  const me = useQuery(queries.me())
  const queryClient = useQueryClient()
  const router = useRouter()
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const main = useRef<HTMLElement>(null)

  useEffect(() => {
    main.current?.focus({ preventScroll: true })
    window.scrollTo(0, 0)
  }, [pathname])

  const logout = useMutation({
    mutationFn: api.logout,
    onSettled: () => signOut(queryClient, router),
  })

  return (
    <>
      <a
        href="#contenido"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-lg focus:bg-card focus:p-3"
      >
        Ir al contenido
      </a>
      <header className="sticky top-0 z-10 border-b-2 bg-card">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-3 px-4 py-3">
          <Link to="/" className={buttonVariants({ variant: 'default', size: 'lg' })}>
            Inicio
          </Link>
          <p className="min-w-0 flex-1 text-base text-muted-foreground">
            {me.data ? (
              <>
                Entró: <strong className="text-foreground">{me.data.name}</strong>
              </>
            ) : null}
          </p>
          <Button
            type="button"
            variant="outline"
            size="lg"
            disabled={logout.isPending}
            onClick={() => logout.mutate()}
          >
            Salir
          </Button>
        </div>
      </header>
      <main
        id="contenido"
        ref={main}
        tabIndex={-1}
        className="mx-auto max-w-5xl px-4 py-6 outline-none"
      >
        <Outlet />
      </main>
    </>
  )
}
