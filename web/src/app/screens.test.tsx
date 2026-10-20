import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { balances, me, mockApi, pageOf, renderApp, saleRow } from '@/test/utils'

describe('lists', () => {
  it('moves through pages with Siguiente and keeps the page in the URL', async () => {
    const user = userEvent.setup()
    const calls = mockApi({
      'GET /api/auth/me': { body: me },
      'GET /api/v1/sales': (call) => {
        const page = Number(call.search.get('page') ?? 1)
        return {
          body: pageOf([saleRow(page, { customer: `Cliente ${page}` })], {
            total: 45,
            page,
          }),
        }
      },
    })

    const { router } = renderApp('/ventas')

    expect(await screen.findByText('Cliente 1')).toBeInTheDocument()
    expect(screen.getByText(/Página 1 de 3/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Anterior' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Siguiente' }))

    expect(await screen.findByText('Cliente 2')).toBeInTheDocument()
    expect(screen.getByText(/Página 2 de 3/)).toBeInTheDocument()
    expect(router.state.location.search).toMatchObject({ page: 2 })
    expect(calls.some((call) => call.path === '/api/v1/sales' && call.search.get('page') === '2')).toBe(true)

    router.history.back()
    expect(await screen.findByText(/Página 1 de 3/)).toBeInTheDocument()
  })

  it('opens directly on the page named in the URL', async () => {
    mockApi({
      'GET /api/auth/me': { body: me },
      'GET /api/v1/sales': (call) => ({
        body: pageOf([saleRow(9, { customer: `Página ${call.search.get('page')}` })], { total: 45, page: 3 }),
      }),
    })

    renderApp('/ventas?page=3')

    expect(await screen.findByText('Página 3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Siguiente' })).toBeDisabled()
  })

  it('shows money in dollars and bolivars and marks a voided sale with its reason', async () => {
    mockApi({
      'GET /api/auth/me': { body: me },
      'GET /api/v1/sales': {
        body: pageOf([
          saleRow(1, { amount_usd: '12.50', amount_bs: '1234.56' }),
          saleRow(2, { customer: 'Pedro', amount_usd: '3.00', voided: true, void_reason: 'Se cobró dos veces' }),
        ]),
      },
    })

    renderApp('/ventas')

    expect(await screen.findByText('$ 12,50')).toBeInTheDocument()
    expect(screen.getByText('Bs. 1.234,56')).toBeInTheDocument()
    const cards = screen.getAllByRole('listitem').filter((item) => within(item).queryByText('Anulada'))
    expect(cards).toHaveLength(1)
    expect(within(cards[0]!).getByText('Motivo: Se cobró dos veces')).toBeInTheDocument()
  })

  it('sends the person back to login when any data call answers 401', async () => {
    mockApi({
      'GET /api/auth/me': { body: me },
      'GET /api/auth/people': { body: [{ name: 'Francisco' }] },
      'GET /api/v1/sales': { status: 401, body: { detail: 'Su sesión venció.' } },
    })

    const { router } = renderApp('/ventas')

    expect(await screen.findByRole('heading', { name: '¿Quién es usted?' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/entrar')
  })

  it('sends a person without a session to login before showing anything', async () => {
    mockApi({
      'GET /api/auth/me': { status: 401, body: { detail: 'Entre otra vez.' } },
      'GET /api/auth/people': { body: [{ name: 'Francisco' }] },
    })

    renderApp('/cierres')

    expect(await screen.findByRole('heading', { name: '¿Quién es usted?' })).toBeInTheDocument()
  })

  it('shows a Spanish error and a retry button when the response has the wrong shape', async () => {
    const user = userEvent.setup()
    let healthy = false
    mockApi({
      'GET /api/auth/me': { body: me },
      'GET /api/v1/sales': () =>
        healthy
          ? { body: pageOf([saleRow(1, { customer: 'Ya funciona' })]) }
          : { body: { items: [{ id: 'uno', amount_usd: 'mucho' }], total: 1, page: 1, page_size: 20 } },
    })

    renderApp('/ventas')

    expect(await screen.findByText(/El servidor respondió algo que no se entiende/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Inicio' })).toBeInTheDocument()

    healthy = true
    await user.click(screen.getByRole('button', { name: 'Intentar de nuevo' }))
    expect(await screen.findByText('Ya funciona')).toBeInTheDocument()
  })
})

describe('home', () => {
  it('shows the three fund balances first and a link to every section', async () => {
    mockApi({
      'GET /api/auth/me': { body: me },
      'GET /api/v1/funds/balances': { body: balances },
    })

    renderApp('/')

    expect(await screen.findByText('$ 1.500,00')).toBeInTheDocument()
    expect(screen.getByText('$ 230,50')).toBeInTheDocument()
    expect(screen.getByText('$ 99,00')).toBeInTheDocument()
    for (const name of ['Ventas', 'Compras', 'Gastos', 'Cajas de huevos', 'Cierres', 'Aportes', 'Movimientos de dinero', 'Dinero', 'Precios de hoy', 'Tasa del dólar', 'Socios']) {
      expect(screen.getByRole('link', { name: new RegExp(`^${name}`) })).toBeInTheDocument()
    }
    expect(screen.getByRole('link', { name: 'Inicio' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Salir' })).toBeInTheDocument()
  })

  it('logs out and returns to the names', async () => {
    const user = userEvent.setup()
    const calls = mockApi({
      'GET /api/auth/me': { body: me },
      'GET /api/auth/people': { body: [{ name: 'Francisco' }] },
      'GET /api/v1/funds/balances': { body: balances },
      'POST /api/auth/logout': { status: 204 },
    })

    renderApp('/')
    await user.click(await screen.findByRole('button', { name: 'Salir' }))

    expect(await screen.findByRole('heading', { name: '¿Quién es usted?' })).toBeInTheDocument()
    expect(calls.some((call) => call.method === 'POST' && call.path === '/api/auth/logout')).toBe(true)
  })
})

describe('date range forms', () => {
  it('refuses an end date before the start date and asks again with a valid range', async () => {
    const user = userEvent.setup()
    const calls = mockApi({
      'GET /api/auth/me': { body: me },
      'GET /api/v1/inventory/ledger': { body: [] },
    })

    const { router } = renderApp('/inventario/movimiento?from=2026-10-01&to=2026-10-20')

    await screen.findByText('No hay movimiento en esas fechas.')
    const to = screen.getByLabelText('Hasta')
    await user.clear(to)
    await user.type(to, '2026-09-01')
    await user.click(screen.getByRole('button', { name: 'Ver' }))
    expect(await screen.findByText(/no puede ser anterior/)).toBeInTheDocument()

    await user.clear(to)
    await user.type(to, '2026-10-10')
    await user.click(screen.getByRole('button', { name: 'Ver' }))

    await screen.findByText('No hay movimiento en esas fechas.')
    expect(router.state.location.search).toMatchObject({ from: '2026-10-01', to: '2026-10-10' })
    expect(calls.at(-1)?.search.get('date_to')).toBe('2026-10-10')
  })
})

describe('list filters', () => {
  it('goes back to page 1 when a day is picked and drops the day with "Ver todos los días"', async () => {
    const user = userEvent.setup()
    const calls = mockApi({
      'GET /api/auth/me': { body: me },
      'GET /api/v1/sales': (call) => ({
        body: pageOf([saleRow(1, { customer: `Página ${call.search.get('page')}` })], { total: 45, page: 3 }),
      }),
    })

    const { router } = renderApp('/ventas?page=3')
    await screen.findByText('Página 3')

    fireEvent.change(screen.getByLabelText('Ver solo un día'), { target: { value: '2026-10-05' } })

    await waitFor(() => expect(router.state.location.search).toEqual({ page: 1, day: '2026-10-05' }))
    await screen.findByText('Página 1')
    expect(calls.at(-1)?.search.get('day')).toBe('2026-10-05')
    expect(calls.at(-1)?.search.get('page')).toBe('1')

    await user.click(screen.getByRole('button', { name: 'Ver todos los días' }))

    await waitFor(() => expect(router.state.location.search).toEqual({ page: 1 }))
    await waitFor(() => expect(calls.at(-1)?.search.has('day')).toBe(false))
    expect(calls.at(-1)?.search.get('page')).toBe('1')
  })

  it('goes back to page 1 when settled boxes are included', async () => {
    const user = userEvent.setup()
    const calls = mockApi({
      'GET /api/auth/me': { body: me },
      'GET /api/v1/boxes': () => ({ body: pageOf([], { total: 45, page: 2 }) }),
    })

    const { router } = renderApp('/cajas?page=2')
    await screen.findByText('No hay cajas para mostrar.')
    expect(calls.at(-1)?.search.has('include_settled')).toBe(false)

    await user.click(screen.getByRole('button', { name: /Mostrar también las cajas/ }))

    await waitFor(() => expect(router.state.location.search).toEqual({ page: 1, settled: true }))
    await waitFor(() => expect(calls.at(-1)?.search.get('include_settled')).toBe('true'))
    expect(calls.at(-1)?.search.get('page')).toBe('1')
  })
})

describe('routes that default their data', () => {
  afterEach(() => vi.useRealTimers())

  it.each([
    ['/inventario/movimiento', '/api/v1/inventory/ledger', []],
    ['/dinero/resumen', '/api/v1/reports/summary', {}],
  ])('%s asks for the month so far when the URL names no dates', async (path, api, body) => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2026, 9, 20, 12))
    const calls = mockApi({
      'GET /api/auth/me': { body: me },
      [`GET ${api}`]: { body },
    })

    renderApp(path)

    await waitFor(() => expect(calls.some((call) => call.path === api)).toBe(true))
    const call = calls.find((item) => item.path === api)
    expect(call?.search.get('date_from')).toBe('2026-10-01')
    expect(call?.search.get('date_to')).toBe('2026-10-20')
    expect(await screen.findByLabelText('Desde')).toHaveValue('2026-10-01')
    expect(screen.getByLabelText('Hasta')).toHaveValue('2026-10-20')
  })
})

describe('box sheet', () => {
  it('asks the server for the sheet of the box named in the URL', async () => {
    const calls = mockApi({ 'GET /api/auth/me': { body: me } })

    renderApp('/cajas/7')

    expect(await screen.findByRole('heading', { name: 'Hoja de la caja 7' })).toBeInTheDocument()
    await waitFor(() => expect(calls.some((call) => call.path === '/api/v1/boxes/7/sheet')).toBe(true))
  })
})

describe('money owed to partners', () => {
  const owed = (id: number) => ({
    id,
    day: '2026-10-04',
    concept: `Gasto ${id}`,
    amount_usd: '5.00',
    rate: '215.50',
    amount_bs: '1077.50',
    paid_by_partner: 'Rosa',
    reimbursed_on: null,
    settled: false,
  })

  it('shows the total of every page and moves through the pages', async () => {
    const user = userEvent.setup()
    const calls = mockApi({
      'GET /api/auth/me': { body: me },
      'GET /api/v1/expenses/owed': (call) => {
        const page = Number(call.search.get('page') ?? 1)
        return { body: { ...pageOf([owed(page)], { total: 45, page }), owed_usd: '225.00' } }
      },
    })

    renderApp('/gastos/pendientes')

    expect(await screen.findByText('Gasto 1')).toBeInTheDocument()
    expect(screen.getByText(/En total se les debe/)).toHaveTextContent('$ 225,00')
    await user.click(screen.getByRole('button', { name: 'Siguiente' }))
    expect(await screen.findByText('Gasto 2')).toBeInTheDocument()
    expect(screen.getByText(/En total se les debe/)).toHaveTextContent('$ 225,00')
    expect(calls.some((call) => call.path === '/api/v1/expenses/owed' && call.search.get('page') === '2')).toBe(true)
  })

  it('says nobody is owed anything when the list is empty', async () => {
    mockApi({
      'GET /api/auth/me': { body: me },
      'GET /api/v1/expenses/owed': { body: { ...pageOf([]), owed_usd: '0.00' } },
    })

    renderApp('/gastos/pendientes')

    expect(await screen.findByText('No se le debe nada a ningún socio.')).toBeInTheDocument()
    expect(screen.queryByText(/En total se les debe/)).not.toBeInTheDocument()
  })
})
