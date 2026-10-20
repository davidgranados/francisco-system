import { z } from 'zod'
import type { DateRange } from '@/api/client'
import { useAppForm } from '@/components/form'

const rangeSchema = z
  .object({
    from: z.string().min(1, 'Elija la fecha desde la que quiere ver.'),
    to: z.string().min(1, 'Elija la fecha hasta la que quiere ver.'),
  })
  .refine((value) => !value.from || !value.to || value.from <= value.to, {
    message: 'La fecha "Hasta" no puede ser anterior a la fecha "Desde".',
    path: ['to'],
  })

export function DateRangeForm({
  value,
  onSubmit,
  submitLabel = 'Ver',
}: {
  value: DateRange
  onSubmit: (range: DateRange) => void
  submitLabel?: string
}) {
  const form = useAppForm({
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
        <form.AppField
          key={name}
          name={name}
          children={(field) => (
            <field.TextField id={`range-${name}`} type="date" label={name === 'from' ? 'Desde' : 'Hasta'} />
          )}
        />
      ))}
      <form.AppForm>
        <form.SubmitButton label={submitLabel} />
      </form.AppForm>
    </form>
  )
}
