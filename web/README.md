# La página web de las cuentas

Una página solo para mirar. Los socios y los usuarios de desarrollo ven las ventas, compras, gastos, cajas de huevos, cierres, aportes, movimientos de dinero, la tasa y los precios, sin escribirle al bot y sin gastar tokens.

Stack: Vite, React 19, TypeScript, TanStack Query, Router y Form, zod y shadcn/ui sobre Tailwind v4.

## Correr en local

Con la API corriendo en `localhost:8000` (ver el `README.md` de la raíz):

```bash
cd web
npm ci
npm run dev
```

Abra la URL que imprime Vite. El dev server manda `/api` a `localhost:8000`.

Sin `TELEGRAM_BOT_TOKEN`, la API no manda el código por Telegram: lo escribe en su log como `login code for <nombre>: 123456`.

## Chequeos

```bash
npm run typecheck
npm run lint
npm test
npm run build
```

CI corre los cuatro en el job `web`.

## Cómo está organizado

- `src/api/schemas.ts` tiene los schemas de zod de cada respuesta. Toda respuesta pasa por ellos en `src/api/client.ts`, y una respuesta con otra forma muestra un error en vez de romper la pantalla.
- `src/api/queries.ts` tiene las queries de TanStack Query. Las listas llevan la página en la key.
- `src/app/router.tsx` tiene las rutas. Las que piden sesión preguntan por `/api/auth/me` antes de cargar.
- `src/app/session.ts` cierra la sesión: va a `/entrar` y borra los datos guardados, menos la lista de nombres.
- `src/lib/labels.ts` traduce cada valor de la API al español que lee el socio.
- `src/screens/` tiene una pantalla por área, y `src/components/ui/` lo que genera el CLI de shadcn.
