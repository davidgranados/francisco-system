import { useForm } from '@tanstack/react-form'
import { z } from 'zod'
import type { DateRange } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const rangeSchema = z
  .object({
    from: z.string().min(1, 'Elija la fecha desde la que quiere ver.'),
    to: z.string().min(1, 'Elija la fecha hasta la que quiere ver.'),
  })
  .refine((value) => !value.from || !value.to || value.from <= value.to, {
    message: 'La fecha "Hasta" no puede ser anterior a la fecha "Desde".',
    path: ['to'],
  })

function errorText(errors: ReadonlyArray<unknown>): string | undefined {
  const first = errors[0]
  if (typeof first === 'string') return first
  if (first && typeof first === 'object' && 'message' in first) return String(first.message)
  return undefined
}

export function DateRangeForm({
  value,
  onSubmit,
  submitLabel = 'Ver',
}: {
  value: DateRange
  onSubmit: (range: DateRange) => void
  submitLabel?: string
}) {
  const form = useForm({
    defaultValues: { from: value.from, to: value.to },
    validators: { onSubmit: rangeSchema },
    onSubmit: ({ value: submitted }) => onSubmit({ from: submitted.from, to: submitted.to }),
  })

  return (
    <form
      noValidate
      className="mb-6 grid gap-4 rounded-xl border-2 bg-card p-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
      onSubmit={(event) => {
        event.preventDefault()
        event.stopPropagation()
        void form.handleSubmit()
      }}
    >
      {(['from', 'to'] as const).map((name) => (
        <form.Field
          key={name}
          name={name}
          children={(field) => {
            const message = errorText(field.state.meta.errors)
            const errorId = `${field.name}-error`
            return (
              <div className="space-y-2">
                <Label htmlFor={`range-${name}`}>{name === 'from' ? 'Desde' : 'Hasta'}</Label>
                <Input
                  id={`range-${name}`}
                  type="date"
                  value={field.state.value}
                  onBlur={field.handleBlur}
                  onChange={(event) => field.handleChange(event.target.value)}
                  aria-invalid={message ? true : undefined}
                  aria-describedby={message ? errorId : undefined}
                />
                {message ? (
                  <p id={errorId} role="alert" className="text-base font-semibold text-destructive">
                    {message}
                  </p>
                ) : null}
              </div>
            )
          }}
        />
      ))}
      <form.Subscribe
        selector={(state) => state.isSubmitting}
        children={(isSubmitting) => (
          <Button type="submit" size="lg" disabled={isSubmitting}>
            {submitLabel}
          </Button>
        )}
      />
    </form>
  )
}
