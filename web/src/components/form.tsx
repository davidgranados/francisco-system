import { createFormHook, createFormHookContexts } from '@tanstack/react-form'
import type { ChangeEvent, ComponentProps } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const { fieldContext, formContext, useFieldContext, useFormContext } = createFormHookContexts()

function issueText(issue: unknown): string | undefined {
  if (typeof issue === 'string') return issue
  if (issue && typeof issue === 'object' && 'message' in issue) return String(issue.message)
  return undefined
}

type InputProps = Omit<ComponentProps<typeof Input>, 'value' | 'onBlur' | 'aria-invalid' | 'aria-describedby'>

function TextField({
  label,
  message,
  format,
  id,
  onChange,
  ...inputProps
}: InputProps & {
  label: string
  message?: string | null
  format?: (value: string) => string
}) {
  const field = useFieldContext<string>()
  const inputId = id ?? field.name
  const errorId = `${inputId}-error`
  const text = message ?? issueText(field.state.meta.errors[0])
  return (
    <div className="space-y-2">
      <Label htmlFor={inputId}>{label}</Label>
      <Input
        {...inputProps}
        id={inputId}
        value={field.state.value}
        onBlur={field.handleBlur}
        onChange={(event: ChangeEvent<HTMLInputElement>) => {
          onChange?.(event)
          field.handleChange(format ? format(event.target.value) : event.target.value)
        }}
        aria-invalid={text ? true : undefined}
        aria-describedby={text ? errorId : undefined}
      />
      {text ? (
        <p id={errorId} role="alert" className="text-lg font-semibold text-destructive">
          {text}
        </p>
      ) : null}
    </div>
  )
}

function SubmitButton({
  label,
  pendingLabel = label,
  className,
}: {
  label: string
  pendingLabel?: string
  className?: string
}) {
  const form = useFormContext()
  return (
    <form.Subscribe
      selector={(state) => state.isSubmitting}
      children={(isSubmitting) => (
        <Button type="submit" size="lg" className={className} disabled={isSubmitting}>
          {isSubmitting ? pendingLabel : label}
        </Button>
      )}
    />
  )
}

export const { useAppForm } = createFormHook({
  fieldComponents: { TextField },
  formComponents: { SubmitButton },
  fieldContext,
  formContext,
})
