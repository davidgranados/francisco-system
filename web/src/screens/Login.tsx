import { useForm } from '@tanstack/react-form'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { z } from 'zod'
import { auth } from '@/api/client'
import { queries } from '@/api/queries'
import { lastName, useSession } from '@/app/session'
import { ErrorNotice, LoadingNotice, QueryState } from '@/components/QueryState'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const codeSchema = z.object({
  code: z.string().regex(/^\d{6}$/, 'El código tiene 6 números. Escríbalos todos.'),
})

function NamePicker({ onPick, pending }: { onPick: (name: string) => void; pending: boolean }) {
  const people = useQuery(queries.people())
  const last = lastName()
  return (
    <section aria-labelledby="who">
      <h1 id="who" className="mb-6 text-3xl font-extrabold">
        ¿Quién es usted?
      </h1>
      <QueryState query={people}>
        {(data) => {
          const ordered = [...data].sort(
            (a, b) => Number(b.name === last) - Number(a.name === last),
          )
          return (
            <ul className="grid gap-4">
              {ordered.map((person) => (
                <li key={person.name}>
                  <Button
                    type="button"
                    size="lg"
                    className="h-20 w-full text-2xl"
                    variant={person.name === last ? 'default' : 'outline'}
                    disabled={pending}
                    onClick={() => onPick(person.name)}
                  >
                    {person.name}
                  </Button>
                  {person.name === last ? (
                    <p className="mt-1 text-base text-muted-foreground">Entró la última vez</p>
                  ) : null}
                </li>
              ))}
            </ul>
          )
        }}
      </QueryState>
    </section>
  )
}

function CodeStep({
  name,
  notice,
  onResend,
  resending,
  onBack,
}: {
  name: string
  notice: string | null
  onResend: () => void
  resending: boolean
  onBack: () => void
}) {
  const session = useSession()
  const login = useMutation({
    mutationFn: (code: string) => auth.login(name, code),
    onSuccess: (me) => session.signIn(me, name),
  })

  const form = useForm({
    defaultValues: { code: '' },
    validators: { onSubmit: codeSchema },
    onSubmit: async ({ value }) => {
      try {
        await login.mutateAsync(value.code)
      } catch {
        form.reset()
      }
    },
  })

  return (
    <section aria-labelledby="code-title">
      <h1 id="code-title" className="mb-2 text-3xl font-extrabold">
        Hola, {name}
      </h1>
      <p className="mb-6 text-xl">Le mandamos un código por Telegram. Escríbalo aquí.</p>
      {notice ? (
        <Alert className="mb-4">
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
      ) : null}
      <form
        noValidate
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault()
          event.stopPropagation()
          void form.handleSubmit()
        }}
      >
        <form.Field
          name="code"
          children={(field) => {
            const issue = field.state.meta.errors[0]
            const clientMessage =
              typeof issue === 'string' ? issue : issue && 'message' in issue ? issue.message : null
            const message = login.error?.message ?? clientMessage
            return (
              <div className="space-y-2">
                <Label htmlFor="code">Código de 6 números</Label>
                <Input
                  id="code"
                  className="h-20 text-center text-4xl tracking-[0.4em]"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  pattern="[0-9]*"
                  value={field.state.value}
                  onBlur={field.handleBlur}
                  onChange={(event) => {
                    login.reset()
                    field.handleChange(event.target.value.replace(/\D/g, ''))
                  }}
                  aria-invalid={message ? true : undefined}
                  aria-describedby={message ? 'code-error' : undefined}
                />
                {message ? (
                  <p id="code-error" role="alert" className="text-lg font-semibold text-destructive">
                    {message}
                  </p>
                ) : null}
              </div>
            )
          }}
        />
        <form.Subscribe
          selector={(state) => state.isSubmitting}
          children={(isSubmitting) => (
            <Button type="submit" size="lg" className="h-20 w-full text-2xl" disabled={isSubmitting}>
              {isSubmitting ? 'Entrando…' : 'Entrar'}
            </Button>
          )}
        />
      </form>
      <div className="mt-6 grid gap-3 sm:grid-cols-2">
        <Button type="button" variant="outline" size="lg" disabled={resending} onClick={onResend}>
          Mandar otro código
        </Button>
        <Button type="button" variant="outline" size="lg" onClick={onBack}>
          Volver
        </Button>
      </div>
    </section>
  )
}

export function LoginScreen() {
  const [name, setName] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const sendCode = useMutation({
    mutationFn: (person: string) => auth.requestCode(person),
    onSuccess: (_result, person) => {
      setName(person)
      setNotice(null)
    },
  })

  const resend = useMutation({
    mutationFn: (person: string) => auth.requestCode(person),
    onSuccess: () => setNotice('Listo, le mandamos otro código. Use el más nuevo.'),
    onError: (error) => setNotice(error.message),
  })

  return (
    <main className="mx-auto max-w-xl px-4 py-10">
      <p className="mb-6 text-xl font-bold text-primary">Cuentas de los huevos</p>
      {name === null ? (
        <>
          {sendCode.isError ? (
            <div className="mb-4">
              <ErrorNotice message={sendCode.error.message} />
            </div>
          ) : null}
          <NamePicker pending={sendCode.isPending} onPick={(person) => sendCode.mutate(person)} />
          {sendCode.isPending ? <LoadingNotice /> : null}
        </>
      ) : (
        <CodeStep
          name={name}
          notice={notice}
          resending={resend.isPending}
          onResend={() => resend.mutate(name)}
          onBack={() => {
            sendCode.reset()
            setName(null)
          }}
        />
      )}
    </main>
  )
}
