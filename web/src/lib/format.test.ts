import { describe, expect, it } from 'vitest'
import { describeEggAmounts, formatBs, formatDay, formatPercent, formatRate, formatUsd } from '@/lib/format'

describe('money and date formatting', () => {
  it('writes dollars with a comma for cents', () => {
    expect(formatUsd(12.5)).toBe('$ 12,50')
  })

  it('writes bolivars with dots for thousands even on four digits', () => {
    expect(formatBs(1234.56)).toBe('Bs. 1.234,56')
    expect(formatBs(1234567.8)).toBe('Bs. 1.234.567,80')
  })

  it('keeps the minus sign in front and hides it on zero', () => {
    expect(formatUsd(-3)).toBe('-$ 3,00')
    expect(formatUsd(-0.001)).toBe('$ 0,00')
  })

  it('writes the rate with up to four decimals', () => {
    expect(formatRate(36.5)).toBe('Bs. 36,50')
    expect(formatRate(36.5123)).toBe('Bs. 36,5123')
  })

  it('writes the weekday and the day first', () => {
    expect(formatDay('2026-10-20')).toBe('mar 20/10/2026')
    expect(formatDay('2026-10-19')).toBe('lun 19/10/2026')
  })

  it('writes a share as a percentage', () => {
    expect(formatPercent(0.5)).toBe('50 %')
  })

  it('describes what was sold in plain words', () => {
    expect(describeEggAmounts({ boxes: 1, cartons: 2, halves: 1, units: 5 })).toBe(
      '1 caja, 2 cartones, 1 medio cartón, 5 huevos sueltos',
    )
  })
})
