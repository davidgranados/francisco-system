import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { balances, me, mockApi, renderApp } from '@/test/utils'

const people = [{ name: 'Francisco' }, { name: 'Maria' }]

describe('login', () => {
  beforeEach(() => localStorage.clear())

  it('sends the code, shows the server message on a wrong one and lands on home with the right one', async () => {
    const user = userEvent.setup()
    let attempts = 0
    const calls = mockApi({
      'GET /api/auth/me': { status: 401, body: { detail: 'Entre otra vez.' } },
      'GET /api/auth/people': { body: people },
      'POST /api/auth/code': { status: 202, body: { expires_in_seconds: 600 } },
      'POST /api/auth/login': () => {
        attempts += 1
        return attempts === 1
          ? { status: 401, body: { detail: 'Ese código no sirve. Pida otro.' } }
          : { body: me }
      },
      'GET /api/v1/funds/balances': { body: balances },
    })

    renderApp('/')

    expect(await screen.findByRole('heading', { name: '¿Quién es usted?' })).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: 'Maria' }))

    expect(await screen.findByText(/Le mandamos un código por Telegram/)).toBeInTheDocument()
    expect(calls.find((call) => call.path === '/api/auth/code')?.body).toEqual({ name: 'Maria' })

    const input = screen.getByLabelText('Código de 6 números')
    expect(input).toHaveAttribute('inputmode', 'numeric')
    expect(input).toHaveAttribute('autocomplete', 'one-time-code')

    await user.type(input, '111111')
    await user.click(screen.getByRole('button', { name: 'Entrar' }))
    expect(await screen.findByText('Ese código no sirve. Pida otro.')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Código de 6 números'), '222222')
    await user.click(screen.getByRole('button', { name: 'Entrar' }))

    expect(await screen.findByRole('heading', { name: 'Inicio' })).toBeInTheDocument()
    expect(await screen.findByText('$ 1.500,00')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Salir' })).toBeInTheDocument()
    expect(localStorage.getItem('ledger.lastName')).toBe('Maria')
    expect(calls.filter((call) => call.path === '/api/auth/login').at(-1)?.body).toEqual({
      name: 'Maria',
      code: '222222',
    })
  })

  it('offers the last name first and refuses a short code without calling the server', async () => {
    const user = userEvent.setup()
    localStorage.setItem('ledger.lastName', 'Maria')
    const calls = mockApi({
      'GET /api/auth/me': { status: 401, body: { detail: 'Entre otra vez.' } },
      'GET /api/auth/people': { body: people },
      'POST /api/auth/code': { status: 202, body: { expires_in_seconds: 600 } },
    })

    renderApp('/entrar')

    const buttons = await screen.findAllByRole('button')
    expect(buttons[0]).toHaveTextContent('Maria')
    await user.click(buttons[0]!)
    await user.type(await screen.findByLabelText('Código de 6 números'), '12')
    await user.click(screen.getByRole('button', { name: 'Entrar' }))

    expect(await screen.findByText('El código tiene 6 números. Escríbalos todos.')).toBeInTheDocument()
    expect(calls.some((call) => call.path === '/api/auth/login')).toBe(false)
  })

  it('goes back to the names and can ask for another code', async () => {
    const user = userEvent.setup()
    const calls = mockApi({
      'GET /api/auth/people': { body: people },
      'POST /api/auth/code': { status: 202, body: { expires_in_seconds: 600 } },
    })

    renderApp('/entrar')
    await user.click(await screen.findByRole('button', { name: 'Francisco' }))
    await user.click(await screen.findByRole('button', { name: 'Mandar otro código' }))
    await waitFor(() => expect(calls.filter((call) => call.path === '/api/auth/code')).toHaveLength(2))
    expect(await screen.findByText(/le mandamos otro código/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Volver' }))
    expect(await screen.findByRole('heading', { name: '¿Quién es usted?' })).toBeInTheDocument()
  })
})

describe('remembered name', () => {
  beforeEach(() => localStorage.clear())

  it('offers the name that logged in first after logging out', async () => {
    const user = userEvent.setup()
    let loggedIn = false
    const unauthorized = { status: 401, body: { detail: 'Entre otra vez.' } }
    mockApi({
      'GET /api/auth/me': () => (loggedIn ? { body: me } : unauthorized),
      'GET /api/auth/people': { body: people },
      'POST /api/auth/code': { status: 202, body: { expires_in_seconds: 600 } },
      'POST /api/auth/login': () => {
        loggedIn = true
        return { body: me }
      },
      'POST /api/auth/logout': () => {
        loggedIn = false
        return { status: 204 }
      },
      'GET /api/v1/funds/balances': { body: balances },
    })

    renderApp('/entrar')
    await user.click(await screen.findByRole('button', { name: 'Maria' }))
    await user.type(await screen.findByLabelText('Código de 6 números'), '123456')
    await user.click(screen.getByRole('button', { name: 'Entrar' }))
    await user.click(await screen.findByRole('button', { name: 'Salir' }))

    const buttons = await screen.findAllByRole('button')
    expect(buttons[0]).toHaveTextContent('Maria')
    expect(screen.getByText('Entró la última vez')).toBeInTheDocument()
  })
})

describe('logout', () => {
  it('lands on the list of names, ready to log in again', async () => {
    const user = userEvent.setup()
    let loggedIn = true
    const unauthorized = { status: 401, body: { detail: 'Su sesión no es válida o ya venció. Entre de nuevo.' } }
    mockApi({
      'GET /api/auth/me': async () => {
        if (loggedIn) return { body: me }
        await new Promise((resolve) => setTimeout(resolve, 20))
        return unauthorized
      },
      'GET /api/v1/funds/balances': () => (loggedIn ? { body: balances } : unauthorized),
      'POST /api/auth/logout': () => {
        loggedIn = false
        return { status: 204 }
      },
      'GET /api/auth/people': async () => {
        await new Promise((resolve) => setTimeout(resolve, 50))
        return { body: [{ name: 'Francisco' }, { name: 'Rosa' }] }
      },
    })

    renderApp('/')
    await user.click(await screen.findByRole('button', { name: 'Salir' }))

    expect(await screen.findByRole('button', { name: 'Rosa' })).toBeInTheDocument()
  })
})
