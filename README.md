# Francisco System

Es la app que lleva las cuentas del negocio de reventa de huevos, con las mismas reglas del cuaderno (`docs/cuaderno.md`). Los socios le escriben a un bot de Telegram en español, por ejemplo "vendí 3 cartones y 4 huevos por pago móvil", y el bot anota compras, ventas, rotos, gastos, la tasa BCV, el cierre y el reparto. Por debajo hay una API REST (FastAPI + PostgreSQL) que hace las mismas cuentas y sirve de respaldo.

El diseño está en `docs/diseno.md`. Los redondeos y la ganancia están hechos para que el ejemplo de la semana del cuaderno (Parte 9) dé exacto, y hay un test que lo repite completo.

## Qué hace

- Cada compra crea cajas numeradas (Caja 1, Caja 2...) con sus precios: costo + 25 %. El cartón y el medio cartón se redondean hacia arriba a $ 0,05, y la unidad al centavo.
- Siempre se vende de la caja abierta más vieja. Si una venta termina una caja, sigue con la siguiente.
- La ganancia de una caja se conoce cuando se termina y ya se compró la siguiente: lo que se vendió menos lo que costó la caja siguiente.
- Las compras se pagan con el capital, que crece con los aportes de los socios. Si no alcanza, la compra se rechaza y el bot dice cuánto falta aportar. Las ventas entran a la caja chica.
- En el cierre:
  - el costo de reponer las cajas cerradas vuelve al capital;
  - se suman las ganancias y se restan los gastos pendientes;
  - se saca una reserva opcional, que va a la caja de ahorros, y una reinversión opcional, que va al capital;
  - lo que queda se reparte según el porcentaje de cada socio;
  - se le devuelve a cada socio lo que pagó de su bolsillo en gastos.
- Los bolívares se calculan con la tasa BCV del día (`ve.dolarapi.com`). Si esa API no responde, se usa la última tasa guardada y el bot avisa.

## Los tres entornos

| | Local | Staging | Producción |
|---|---|---|---|
| Dónde corre | Tu máquina | Railway, entorno `staging` | Railway, entorno `production` |
| Base de datos | Postgres 18 en `docker compose` | Un Postgres propio en Railway | Un Postgres propio en Railway |
| Bot de Telegram | Apagado, o uno tuyo con un túnel | El bot de pruebas | El bot de los socios |
| Cómo se hace el deploy | `uv run uvicorn ...` | Solo, con cada push a `main` | Solo al publicar un release en GitHub |
| Quién lo usa | Quien programa | Los socios y los usuarios de desarrollo, para probar | Los socios, con las cuentas de verdad |

Cada entorno tiene su propia base y su propio bot. No comparten nada: lo que anotes en staging no aparece en producción.

## Correr en local

Necesitas Docker y [uv](https://docs.astral.sh/uv/).

1. Levanta la base y arma la configuración:

   ```bash
   docker compose up -d                 # PostgreSQL 18 en localhost:5432
   cp .env.example .env                 # y cambia API_KEYS
   uv sync
   ```

2. Llena la base. Puedes empezar con una vacía:

   ```bash
   uv run alembic upgrade head
   uv run python -m app.seed "Socio A:0.60:123456789" "Socio B:0.40:987654321"
   ```

   O con una copia de staging, si tienes `STAGING_DATABASE_URL` en `.env` (mira [Reiniciar o copiar una base](#reiniciar-o-copiar-una-base)):

   ```bash
   uv run python -m app.restore_db --from staging --to local
   uv run alembic upgrade head
   ```

3. Arranca la app:

   ```bash
   uv run uvicorn app.main:app --reload
   ```

La documentación de la API, donde se puede probar cada endpoint, queda en http://localhost:8000/docs. Todo lo que está bajo `/api/v1` pide el header `X-API-Key` con una de las claves de `API_KEYS`:

```bash
curl -H "X-API-Key: cambie-esta-clave" http://localhost:8000/api/v1/inventory/stock
```

Si no pones `TELEGRAM_BOT_TOKEN` y `TELEGRAM_WEBHOOK_SECRET`, el bot queda apagado y la API funciona igual.

Para probar el bot en local:
- Crea un bot tuyo con BotFather. Nunca uses el token de staging o de producción: al arrancar, la app le apunta el webhook de ese bot a tu máquina.
- En `PUBLIC_URL` pon una URL pública con HTTPS, por ejemplo la de un túnel hacia `localhost:8000`.

### Los socios

A `python -m app.seed` le pasas la lista completa de socios activos, cada uno como `Nombre:porcentaje:telegram_id`. Los porcentajes tienen que sumar 1. El id de Telegram es opcional, pero un socio sin id no puede usar el bot. Si lo corres otra vez con lo mismo, no cambia nada. Un socio que no esté en la lista queda inactivo.

Para saber tu id de Telegram, escríbele a [@userinfobot](https://t.me/userinfobot).

## Reiniciar o copiar una base

Son dos comandos para desarrollo, y se corren desde tu checkout:

```bash
uv run python -m app.reset_db local                                  # o staging
uv run python -m app.restore_db --from production --to local         # el origen puede ser local, staging o production
```

**`reset_db`** borra todo lo que hay en la base y le corre las migrations de tu checkout. Si es staging, tu checkout tiene que estar en `main`.

**`restore_db`** saca un dump del origen y lo restaura en el destino, que queda igual al origen. El dump se saca antes de tocar el destino, así que si falla, el destino queda como estaba. Si copiaste a local y tu checkout trae migrations nuevas, corre después `uv run alembic upgrade head`.

**Producción nunca se sobrescribe:**
- `production` no está entre los destinos que aceptan los comandos.
- Si la URL de destino apunta a la misma base que `PRODUCTION_DATABASE_URL`, el comando se niega.
- Ninguno de los dos corre dentro de Railway.
- Antes de borrar, te piden escribir el nombre del destino. Con `--yes` no preguntan.

**Las URLs** van en `.env`: `DATABASE_URL` para local, más `STAGING_DATABASE_URL` y `PRODUCTION_DATABASE_URL`.
- Desde fuera de Railway no se llega a sus bases hasta que les activas un TCP proxy (Railway → servicio Postgres → **Settings → Networking → TCP Proxy**).
- La URL que tienes que copiar es la de `DATABASE_PUBLIC_URL`.
- Ese proxy deja la base abierta a internet, protegida solo por su contraseña. Quítalo cuando termines.

**`pg_dump` y `pg_restore`** corren dentro del container `postgres` de `docker compose`, que usa Postgres 18 igual que Railway. Hace falta así porque `pg_dump` se niega a sacar el dump de un servidor más nuevo que él. Si prefieres usar los que tienes instalados, deja `PG_TOOLS=` vacío.

**Si tu base local estaba en Postgres 16**, ese volumen viejo (`postgres-data`) ya no se usa, y `docker compose up -d` arranca uno nuevo vacío. Llénalo con `reset_db local` o con `restore_db`. El viejo lo borras con `docker volume rm francisco-system_postgres-data`.

## Tests

```bash
docker compose up -d
uv run pytest -q
uv run ruff format --check . && uv run ruff check .
```

Los tests crean una base `francisco_test` en el mismo Postgres (la puedes cambiar con `TEST_DATABASE_URL`) y le corren las migrations. No salen a internet: la tasa BCV y Anthropic se reemplazan por versiones de mentira.

## El eval del bot

`evals/casos.yaml` tiene 58 conversaciones de socios, por ejemplo:
- ventas, compras, gastos, rotos, conteos, la tasa, aportes y consultas;
- el cierre con sus botones y las correcciones;
- mensajes a los que les falta un dato;
- charla que no tiene que ver con el negocio y casos tramposos.

Cada caso dice:
- con qué datos arranca;
- qué herramientas tiene que llamar el bot y qué no puede hacer;
- cómo tiene que quedar la base;
- qué tiene que decir la respuesta.

La nota se pone sin usar un modelo: se miran las llamadas, la base y las palabras de la respuesta.

Para comparar modelos con la API de verdad (esto gasta tokens):

```bash
docker compose up -d
export ANTHROPIC_API_KEY=...
uv run python -m evals.run --model claude-haiku-5-5 --model claude-sonnet-5-5 --repeat 3
```

Muestra, para cada modelo:
- cuántas corridas pasaron, en total y por categoría;
- cuántos tokens usa en promedio, de entrada, de salida y de cache;
- cuánto cuesta cada conversación, en USD aproximados;
- cuánto tarda cada turno, en p50 y p95.

El detalle, con las conversaciones, queda guardado en `evals/resultados/`, que no se sube al repo. Si algún modelo pasa menos del 90 % de las corridas, el comando termina con código 1. Para cambiar ese límite, usa `--threshold 0.8`.

Otras opciones:
- `--case venta_pago_movil` o `--category cierre` para correr solo una parte;
- `--effort low` y `--thinking off` para probar otra configuración;
- `--concurrency 4`.

`uv run python -m evals.run --golden` corre todo sin internet, con un cliente de mentira que hace exactamente lo que espera cada caso. Sirve para comprobar que el eval funciona, y `tests/test_evals.py` lo corre en cada `pytest`. Cada corrida usa una base nueva, copiada de `francisco_eval_plantilla` (la puedes cambiar con `EVAL_DATABASE_URL`).

Lo que se investigó para preparar el bot para Haiku, con las fuentes, está en `docs/investigacion-haiku.md`.

## Montar un entorno en Railway

Staging y producción están en el mismo proyecto de Railway, `francisco-system`, como dos entornos. Cada uno tiene su servicio de la app, que se construye con el `Dockerfile`, y su propio Postgres. No hay `railway.toml`, porque Railway ya no lo acepta en servicios nuevos. Todo se configura en el panel.

Estos pasos sirven para montar cualquiera de los dos. Más abajo, [Staging](#staging) y [Producción](#producción) dicen qué tiene de distinto cada uno. En `docs/despliegue.md` está el detalle de cómo se hace el deploy, cómo se saca un hotfix y cómo se configura GitHub.

### 1. El bot en Telegram

Cada entorno necesita su propio bot. Si dos entornos usan el mismo token, en cada deploy uno le quita el webhook al otro.

1. En Telegram, abre [@BotFather](https://t.me/BotFather) y manda `/newbot`.
2. Ponle el nombre que se va a ver (por ejemplo "Cuentas Huevos") y un usuario que termine en `bot`.
3. BotFather te da un token, algo como `123456:ABC-...`. Ese es `TELEGRAM_BOT_TOKEN`. No se lo pases a nadie.
4. Inventa el secreto del webhook. Puede tener letras, números, `_` o `-`:

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   Ese es `TELEGRAM_WEBHOOK_SECRET`.

### 2. El proyecto en Railway

1. Si el proyecto no existe, créalo en [railway.com](https://railway.com). Si ya existe, elige el entorno arriba a la izquierda, o crea uno nuevo con **New Environment**.
2. Agrega una base en ese entorno: **New → Database → PostgreSQL**.
3. Agrega el servicio de la app: **New → GitHub Repo**, y elige este repo. Railway encuentra el `Dockerfile` y lo usa para construir. En producción, después hay que desconectarlo del repo (mira [Producción](#producción)).

### 3. El dominio

En el servicio de la app: **Settings → Networking → Generate Domain**. Te queda algo como `https://francisco-system-production.up.railway.app`. Telegram manda los mensajes a `https://<dominio>/telegram/webhook`.

### 4. Las variables

En el servicio de la app, **Variables**:

| Variable | Valor |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}`. Es una referencia a la base. La app acepta `postgresql://` y la convierte sola |
| `API_KEYS` | `francisco:una-clave-larga,otro:otra-clave` |
| `TELEGRAM_BOT_TOKEN` | El token que te dio BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | El secreto del paso 1 |
| `PUBLIC_URL` | `https://<dominio del paso 3>`, sin `/` al final. Si no la pones, la app usa `RAILWAY_PUBLIC_DOMAIN`, que Railway agrega cuando el servicio tiene dominio |
| `ANTHROPIC_API_KEY` | Tu clave de la consola de Anthropic |
| `ANTHROPIC_MODEL` | Opcional. Por defecto es `claude-sonnet-5-5`. `claude-haiku-5-5` cuesta unas 20 veces menos, pero corre el eval antes de cambiarlo |
| `ANTHROPIC_EFFORT` | Opcional: `low`, `medium`, `high`, `xhigh` o `max`. Si lo dejas vacío, es `medium` |
| `ANTHROPIC_THINKING` | Opcional: `adaptive` (por defecto) u `off`. `off` solo funciona con esfuerzo hasta `high` |
| `DEV_TELEGRAM_USERS` | Opcional y solo para staging: `David:820460532,Otro:123` (mira [Usuarios de desarrollo](#usuarios-de-desarrollo)) |
| `MARKUP` | Opcional. Por defecto es `0.25` |
| `TIMEZONE` | Opcional. Por defecto es `America/Caracas`, y es lo que decide qué día es "hoy" |

`PORT` lo pone Railway, no lo toques.

### 5. Comandos y healthcheck

En **Settings → Deploy**:

- **Pre-deploy Command**: `alembic upgrade head`. Corre las migrations antes de cada deploy. Si fallan, el deploy se cancela y se queda la versión anterior.
- **Custom Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. El `Dockerfile` ya arranca así, así que lo puedes dejar vacío.
- **Healthcheck Path**: `/healthz`. Responde `{"status": "ok"}` cuando la app está arriba y se puede conectar a la base.

Haz el deploy. Cuando la app arranca, registra sola el webhook en Telegram con el secreto.

### 6. Cargar los socios

Con la [CLI de Railway](https://docs.railway.com/guides/cli), dentro del servicio:

```bash
railway ssh
python -m app.seed "Socio A:0.60:123456789" "Socio B:0.40:987654321"
```

O desde tu máquina, con la URL pública de la base (Postgres → Variables → `DATABASE_PUBLIC_URL`). Para esto necesitas el TCP proxy de la base activado. Quítalo cuando termines:

```bash
DATABASE_URL="<DATABASE_PUBLIC_URL>" uv run python -m app.seed "Socio A:0.60:123456789" "Socio B:0.40:987654321"
```

### 7. Probar

- `https://<dominio>/healthz` tiene que responder `{"status":"ok"}`.
- `https://api.telegram.org/bot<TOKEN>/getWebhookInfo` tiene que mostrar la URL del webhook y `pending_update_count` en 0.
- Mándale `/start` al bot desde la cuenta de un socio. Si le escribe alguien que no es socio, el bot no contesta.

## Staging

Aquí se prueba todo antes de que llegue a los socios. Hoy está en `https://francisco-system-staging.up.railway.app`, y su bot es `@venta_de_huevos_staging_bot`.

- **El deploy es automático.** El servicio está conectado al repo, en el branch `main` (**Settings → Source**). Cada push o merge a `main` hace deploy en segundos, sin esperar al CI de GitHub. O sea, puede quedar corriendo un commit con el CI en rojo. Antes de dar algo por probado, revisa el CI.
- **Usuarios de desarrollo.** Pon en `DEV_TELEGRAM_USERS` a quienes van a probar (mira [Usuarios de desarrollo](#usuarios-de-desarrollo)).
- **Socios de prueba.** Cárgalos con `python -m app.seed` como en el paso 6, con los ids de Telegram de quienes prueban.
- **Empezar de cero.**
  - `uv run python -m app.reset_db staging`, desde un checkout en `main`, deja la base vacía y con las migrations corridas.
  - `uv run python -m app.restore_db --from production --to staging` la deja igual a producción.
  - Los dos necesitan el TCP proxy de la base (mira [Reiniciar o copiar una base](#reiniciar-o-copiar-una-base)).

## Producción

Es la que usan los socios, con las cuentas de verdad. Hoy está en `https://francisco-system-production.up.railway.app`.

- **No está conectada al repo.** Un push o un merge a `main` nunca la toca. En **Settings → Source** no tiene que haber ningún repo. Si aparece uno, desconéctalo.
- **El deploy se hace publicando un release en GitHub.**
  - Publicar un release **es** hacer el deploy.
  - El workflow `.github/workflows/prod-deployment.yml` corre el CI sobre el tag. Si pasa, sube ese código a Railway con `railway up`.
  - Si algo falla, el workflow borra el release y el tag.

  ```bash
  gh release create v0.2.0 --target main --generate-notes
  ```

- **Lo que se configura una sola vez.**
  - En Railway, un token del entorno `production` (proyecto → **Settings → Tokens**).
  - En GitHub (repo → **Settings → Secrets and variables → Actions**), ese token como el secret `RAILWAY_PRODUCTION_TOKEN`, y la variable `RAILWAY_SERVICE` = `francisco-system`.
  - El detalle está en `docs/despliegue.md`.
- **Sin usuarios de desarrollo.** Deja `DEV_TELEGRAM_USERS` vacío, porque todo lo que anote un usuario de desarrollo entra en las cuentas de verdad.
- **Antes del primer release con capital y caja chica.**
  - Las compras se pagan con el capital, y se rechaza cualquier compra o cierre que deje un fondo en negativo.
  - Si en producción hay compras que ningún aporte cubre, registra un aporte de apertura apenas termine el deploy. Por el bot es algo como "Socio A aportó 500".
  - Para ver antes cómo va a quedar:
    1. copia producción a local con `restore_db --from production --to local`;
    2. corre `alembic upgrade head`;
    3. mira los fondos en `GET /api/v1/reports/cash`.
- **Volver atrás no arregla la base.** Las migrations corren en el Pre-deploy Command, antes de que arranque la versión nueva. Si haces deploy de un tag anterior, los cambios que las migrations le hicieron a la base se quedan.

## Usuarios de desarrollo

`DEV_TELEGRAM_USERS="David:820460532,Otro:123"` deja usar el bot a gente que no es socia. Son pares `nombre:id_de_telegram` separados por comas. Si lo dejas vacío, no hay ninguno.

Los usuarios de desarrollo:
- no tienen porcentaje, no entran en el reparto y no están en la tabla de socios;
- pueden hacer todo lo que hace un socio, incluidos `/start`, `/nuevo` y los botones Confirmar y Cancelar.

Reglas:
- Una operación preparada solo la puede confirmar quien la pidió.
- No se pueden repetir ni el nombre ni el id.
- Si el valor está mal escrito, la app no arranca.
- Si el id de un usuario de desarrollo es el de un socio activo, cuenta como socio.

Para un usuario de desarrollo, "yo" no es ningún socio. Si dice "pagué yo", el bot le pregunta de qué socio habla. Úsalos en staging, nunca en producción, porque lo que anoten entra en las cuentas de verdad.

## Usar el bot

Se le habla normal. Algunos ejemplos:

- "Hoy compré 2 cajas a 63 en efectivo dólares, en Granja X."
- "Vendí 3 cartones y 4 sueltos, pago móvil." o "Me compraron la caja completa por punto."
- "Se partieron 3." o "Le di 2 de ñapa a la vecina."
- "Pagué yo el transporte, 1,50." o "Pagué 350 Bs de bolsas con plata del negocio."
- "Conté y hay 8 cartones y 6 sueltos."
- "¿Cuántos huevos quedan?" o "Pásame la lista de precios de hoy."
- "¿Cuánto ganó la caja 1?"
- "¿Cuánto nos toca?"

Con "¿Cuánto nos toca?", el bot muestra el cierre con el reparto y dos botones, Confirmar y Cancelar.
- Solo se guarda cuando el socio que lo pidió toca Confirmar. Escribir "sí" no lo guarda.
- Los botones sirven una sola vez y vencen a los 15 minutos.

Anular una venta o una compra funciona igual, con botones. Si al bot le falta un dato (por ejemplo cómo te pagaron), te lo pregunta antes de anotar. `/nuevo` borra la conversación con el bot, pero no borra nada de lo anotado.

## La página web

La misma URL del servicio abre una página para mirar las cuentas: ventas, compras, gastos, cajas de huevos, existencia, cierres, aportes, movimientos de dinero, la plata de cada fondo, la tasa y los precios. Solo se lee. Para anotar algo se sigue usando el bot.

Para entrar:

1. La persona toca su nombre. Aparecen los socios activos con Telegram y los usuarios de `DEV_TELEGRAM_USERS`.
2. El bot le manda un código de 6 números por Telegram. Vence en 10 minutos, y con 5 errores hay que pedir otro. Entre un pedido y otro tiene que pasar un minuto.
3. La persona escribe el código y queda adentro 90 días en ese navegador.

El bot solo puede escribirle a quien ya tocó «Iniciar» en el chat. Si un socio se desactiva, su sesión deja de servir en el siguiente pedido.

La sesión es una cookie, y con ella solo se puede leer: cualquier cambio por la API sigue pidiendo `X-API-Key`. Las listas vienen por páginas (`?page=1&page_size=20`, hasta 100 por página). El código de la página está en `web/`, y su `README.md` dice cómo correrla en local. El `Dockerfile` la construye y la API la sirve en el mismo dominio.

## Cómo está organizado el código

- `app/domain/rules.py` tiene las reglas sin base de datos: precios, redondeo, PEPS, reparto y estados de la caja.
- `app/services/` tiene toda la lógica del negocio. La API y el bot llaman a las mismas funciones.
- `app/api/` tiene un router por servicio, bajo `/api/v1`, y `app/api/auth.py` la entrada a la página web.
- `app/web.py` sirve la página web ya construida.
- `web/` tiene la página web en React.
- `app/agent/` tiene:
  - las herramientas y el prompt del bot;
  - el loop con Claude;
  - las acciones que esperan el botón Confirmar;
  - el webhook de Telegram.
- `evals/` tiene los casos del eval y el programa que los corre.
- `alembic/` tiene las migrations, y `app/seed.py` carga los socios.
