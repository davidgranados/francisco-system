# Francisco System

Las cuentas del negocio de reventa de huevos, tal como las describe el cuaderno (`docs/cuaderno.md`), en una app. Los socios hablan con un bot de Telegram en español ("vendí 3 cartones y 4 huevos por pago móvil") y el bot registra compras, ventas, rotos, gastos, la tasa BCV, el cierre y el reparto. Debajo hay una API REST (FastAPI + PostgreSQL) que hace las mismas cuentas y sirve de respaldo.

El diseño está en `docs/diseno.md`. Las reglas de redondeo y de ganancia son las que hacen que el ejemplo de la semana del cuaderno (Parte 9) dé exacto, y una prueba lo reproduce completo.

## Qué hace

- Cada compra crea cajas numeradas (Caja 1, Caja 2...) con sus precios: costo + 25 %, cartón y medio redondeados hacia arriba a $ 0,05 y la unidad al centavo.
- Se vende siempre de la caja abierta más vieja. Una venta que agota una caja sigue en la siguiente.
- La ganancia de una caja aparece cuando se terminó y ya se compró la siguiente: ventas reales menos el costo de la caja siguiente.
- El cierre suma esas ganancias, resta los gastos pendientes y una reserva opcional, y reparte según el porcentaje de cada socio. Devuelve lo que un socio pagó de su bolsillo.
- Los bolívares salen de la tasa BCV del día (`ve.dolarapi.com`). Si la API no responde se usa la última tasa guardada y se avisa.

## Correr en local

Necesita Docker y [uv](https://docs.astral.sh/uv/).

```bash
docker compose up -d                 # PostgreSQL 16 en localhost:5432
cp .env.example .env                 # y edite API_KEYS
uv sync
uv run alembic upgrade head
uv run python -m app.seed "Socio A:0.60:123456789" "Socio B:0.40:987654321"
uv run uvicorn app.main:app --reload
```

La documentación interactiva de la API queda en http://localhost:8000/docs. Todas las rutas bajo `/api/v1` piden la cabecera `X-API-Key` con una de las claves de `API_KEYS`:

```bash
curl -H "X-API-Key: cambie-esta-clave" http://localhost:8000/api/v1/inventory/stock
```

Sin `TELEGRAM_BOT_TOKEN` y `TELEGRAM_WEBHOOK_SECRET` el bot queda apagado y la API funciona igual. Para probar el bot en local hace falta una URL pública con HTTPS (por ejemplo un túnel) puesta en `PUBLIC_URL`.

### Los socios

`python -m app.seed` recibe la lista completa de socios activos, cada uno como `Nombre:porcentaje:telegram_id`. Los porcentajes deben sumar 1. El id de Telegram es opcional, pero sin él ese socio no puede usar el bot. Correrlo otra vez con lo mismo no cambia nada, y un socio que no esté en la lista queda inactivo.

Para saber su id de Telegram, escríbale a [@userinfobot](https://t.me/userinfobot).

## Pruebas

```bash
docker compose up -d
uv run pytest -q
uv run ruff format --check . && uv run ruff check .
```

Las pruebas crean una base `francisco_test` en el mismo Postgres (se puede cambiar con `TEST_DATABASE_URL`), le aplican las migraciones y no salen a internet: la tasa BCV y Anthropic se reemplazan por dobles.

## El eval del bot

`evals/casos.yaml` tiene 58 conversaciones de socios (ventas, compras, gastos, rotos, conteos, tasa, aportes, consultas, el cierre con sus botones, correcciones, mensajes a los que les falta un dato, charla que no es del negocio y casos tramposos). Cada caso dice de qué estado arranca, qué herramientas tiene que llamar el bot, qué no puede hacer, cómo tiene que quedar la base y qué tiene que decir la respuesta. Se califica sin modelo: llamadas, base de datos y palabras.

Para comparar modelos con la API real (gasta tokens):

```bash
docker compose up -d
export ANTHROPIC_API_KEY=...
uv run python -m evals.run --model claude-haiku-5-5 --model claude-sonnet-5-5 --repeat 3
```

Imprime, por modelo, cuántas corridas pasaron (en total y por categoría), los tokens promedio de entrada, salida y cache, el costo estimado en USD por conversación y la latencia p50/p95 por turno, y guarda el detalle con las conversaciones en `evals/resultados/` (no se sube al repositorio). Sale con código 1 si algún modelo pasa menos del 90 % (`--threshold 0.8` para cambiarlo). Otras opciones: `--case venta_pago_movil` o `--category cierre` para correr una parte, `--effort low` y `--thinking off` para probar otra configuración, `--concurrency 4`.

`uv run python -m evals.run --golden` corre todo sin red con un cliente guionado que hace lo que cada caso espera. Sirve para comprobar que el eval funciona; la prueba `tests/test_evals.py` lo hace en cada `pytest`. Cada corrida usa una base nueva clonada de `francisco_eval_plantilla` (se cambia con `EVAL_DATABASE_URL`).

Lo que se investigó para preparar el bot para Haiku, con las fuentes, está en `docs/investigacion-haiku.md`.

## Desplegar en Railway, paso a paso

La app es un solo servicio con su `Dockerfile` y una base PostgreSQL de Railway. No usa `railway.toml` (Railway lo dejó de aceptar para servicios nuevos); todo se configura en el panel.

Hay dos entornos. `staging` se despliega solo con cada push a `main`. `production` se despliega únicamente al publicar un release en GitHub; publicar un release **es** desplegar. El flujo completo, los hotfix y la configuración están en `docs/despliegue.md`. Los pasos de abajo sirven para montar cualquiera de los dos entornos.

### 1. El bot en Telegram

1. En Telegram, abra [@BotFather](https://t.me/BotFather) y mande `/newbot`.
2. Elija el nombre que se ve (por ejemplo "Cuentas Huevos") y un usuario que termine en `bot`.
3. BotFather le da un token como `123456:ABC-...`. Ese es `TELEGRAM_BOT_TOKEN`. No lo comparta.
4. Invente el secreto del webhook, con letras, números, `_` o `-`:

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   Ese es `TELEGRAM_WEBHOOK_SECRET`.

### 2. El proyecto en Railway

1. Cree un proyecto nuevo en [railway.com](https://railway.com).
2. Agregue una base de datos: **New → Database → PostgreSQL**.
3. Agregue el servicio de la app: **New → GitHub Repo** y elija este repositorio. Railway ve el `Dockerfile` y lo usa para construir.

### 3. El dominio público

En el servicio de la app: **Settings → Networking → Generate Domain**. Queda algo como `https://francisco-system-production.up.railway.app`. Telegram manda los mensajes a `https://<dominio>/telegram/webhook`.

### 4. Las variables

En el servicio de la app, **Variables**:

| Variable | Valor |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (referencia a la base; la app acepta `postgresql://` y lo convierte sola) |
| `API_KEYS` | `francisco:una-clave-larga,otro:otra-clave` |
| `TELEGRAM_BOT_TOKEN` | el token de BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | el secreto del paso 1 |
| `PUBLIC_URL` | `https://<dominio del paso 3>`, sin barra final. Si no se pone, la app usa `RAILWAY_PUBLIC_DOMAIN`, que Railway agrega cuando el servicio tiene dominio |
| `ANTHROPIC_API_KEY` | su clave de la consola de Anthropic |
| `ANTHROPIC_MODEL` | opcional, por defecto `claude-sonnet-5-5`. `claude-haiku-5-5` cuesta unas 20 veces menos; corra el eval antes de cambiarlo |
| `ANTHROPIC_EFFORT` | opcional: `low`, `medium`, `high`, `xhigh` o `max`. Vacío es `medium` |
| `ANTHROPIC_THINKING` | opcional: `adaptive` (por defecto) u `off` (solo con esfuerzo hasta `high`) |
| `DEV_TELEGRAM_USERS` | opcional, usuarios de desarrollo: `David:820460532,Otro:123` (ver abajo) |
| `MARKUP` | opcional, por defecto `0.25` |
| `TIMEZONE` | opcional, por defecto `America/Caracas` (define qué es "hoy") |

`PORT` lo pone Railway; no lo toque.

### 5. Comandos y healthcheck

En **Settings → Deploy**:

- **Pre-deploy Command**: `alembic upgrade head`. Corre las migraciones antes de cada despliegue; si fallan, el despliegue se cancela y sigue la versión anterior.
- **Custom Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. El `Dockerfile` ya arranca así, de modo que se puede dejar vacío.
- **Healthcheck Path**: `/healthz`. Responde `{"status": "ok"}` cuando la app está arriba y llega a la base.

Despliegue. Al arrancar, la app registra sola el webhook en Telegram con el secreto.

### 6. Cargar los socios

Con la [CLI de Railway](https://docs.railway.com/guides/cli), dentro del servicio:

```bash
railway ssh
python -m app.seed "Socio A:0.60:123456789" "Socio B:0.40:987654321"
```

O desde su máquina, con la URL pública de la base (Postgres → Variables → `DATABASE_PUBLIC_URL`; requiere tener activado el acceso público de la base):

```bash
DATABASE_URL="<DATABASE_PUBLIC_URL>" uv run python -m app.seed "Socio A:0.60:123456789" "Socio B:0.40:987654321"
```

### 7. Probar

- `https://<dominio>/healthz` debe responder `{"status":"ok"}`.
- `https://api.telegram.org/bot<TOKEN>/getWebhookInfo` debe mostrar la URL del webhook y `pending_update_count` en 0.
- Escríbale `/start` al bot desde la cuenta de un socio. Si escribe alguien que no es socio, el bot no contesta.

### Usuarios de desarrollo

`DEV_TELEGRAM_USERS="David:820460532,Otro:123"` (pares `nombre:id_de_telegram` separados por comas; vacío es ninguno) deja usar el bot a personas que no son socios: no tienen porcentaje, no entran en el reparto y no están en la tabla de socios, pero pueden hacer todo lo que hace un socio, incluidos `/start`, `/nuevo` y los botones Confirmar y Cancelar. Cada operación preparada solo la confirma quien la pidió. El nombre y el id no se pueden repetir, y un valor mal escrito impide que la app arranque. Si el id de un usuario de desarrollo es el de un socio activo, gana el socio.

Para un usuario de desarrollo, "yo" no es ningún socio: si dice "pagué yo", el bot le pregunta a qué socio se refiere. Úselos en el ambiente de staging y no en producción, porque lo que registren entra en las cuentas reales.

## Usar el bot

Se le habla normal. Algunos ejemplos:

- "Hoy compré 2 cajas a 63 en efectivo dólares, en Granja X."
- "Vendí 3 cartones y 4 sueltos, pago móvil." o "Me compraron la caja completa por punto."
- "Se partieron 3." o "Le di 2 de ñapa a la vecina."
- "Pagué yo el transporte, 1,50." o "Pagué 350 Bs de bolsas con plata del negocio."
- "Conté y hay 8 cartones y 6 sueltos."
- "¿Cuántos huevos quedan?" o "Pásame la lista de precios de hoy."
- "¿Cuánto ganó la caja 1?"
- "¿Cuánto nos toca?" El bot muestra el cierre con el reparto y dos botones, Confirmar y Cancelar. Solo se guarda cuando el socio que lo pidió toca Confirmar; escribir "sí" no lo guarda. Los botones sirven una sola vez y vencen a los 15 minutos.

Anular una venta o una compra funciona igual, con botones. Si al bot le falta un dato (por ejemplo cómo le pagaron), pregunta antes de anotar. `/nuevo` borra la conversación con el bot (no borra ningún registro).

## Estructura

- `app/domain/rules.py`: las reglas puras (precios, redondeo, PEPS, reparto, estados de la caja).
- `app/services/`: toda la lógica del negocio. La API y el bot llaman a las mismas funciones.
- `app/api/`: un router por servicio bajo `/api/v1`.
- `app/agent/`: las herramientas del bot, el bucle con Claude, el prompt, las acciones que esperan el botón Confirmar y el webhook de Telegram.
- `evals/`: los casos del eval y el programa que los corre.
- `alembic/`: migraciones. `app/seed.py`: carga de socios.
