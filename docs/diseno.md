# Diseño de Francisco System

App a medida para el negocio de reventa de huevos descrito en `docs/cuaderno.md`. Una API REST (FastAPI + PostgreSQL) y, encima de ella, un agente conversacional en Telegram que maneja compras, ventas, inventario, gastos, tasa BCV, cierres y reparto en lenguaje natural. Se despliega en Railway como un solo servicio más una base Postgres de Railway.

## Stack

- Python 3.13, `uv` (pyproject + uv.lock + .python-version).
- FastAPI 0.146, uvicorn, pydantic 2, pydantic-settings.
- SQLAlchemy 2.1 async + asyncpg, Alembic (plantilla async). Dinero en `Numeric`, nunca float.
- python-telegram-bot 22 en modo webhook dentro de la app FastAPI (`updater(None)`), con `secret_token`.
- anthropic SDK, bucle manual de tool use sobre `messages.create`, modelo configurable (`claude-sonnet-5-5` por defecto; preparado para `claude-haiku-5-5`, ver `docs/investigacion-haiku.md`), *thinking* y esfuerzo explícitos en cada request, prompt caching en tools + system.
- httpx para la tasa BCV (`https://ve.dolarapi.com/v1/dolares/oficial`, campo `promedio`).
- Railway: Dockerfile (railway.toml está deprecado para servicios nuevos). Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Pre-deploy: `alembic upgrade head`. Healthcheck `/healthz`.

## Usuarios y auth

Muy pocos usuarios, que son los socios. La tabla `partners` guarda nombre, porcentaje del reparto y `telegram_user_id`.

- Telegram: solo responden los `telegram_user_id` de socios activos. El resto recibe silencio.
- API REST: cabecera `X-API-Key`. Las claves salen de la variable `API_KEYS="nombre:clave,nombre:clave"` y se comparan con `secrets.compare_digest`. No hay registro, login ni JWT.
- El webhook de Telegram valida `X-Telegram-Bot-Api-Secret-Token`.

## Modelo del dominio

La unidad de todo es la **caja** (360 huevos). Una compra crea N cajas numeradas en orden global (Caja 1, Caja 2...). Se vende PEPS: siempre la caja abierta más vieja, una a la vez.

### Unidades

`Presentation` enum con huevos por presentación: `caja=360`, `carton=30`, `medio=15`, `unidad=1`. Todo el inventario se cuenta en huevos (enteros).

### Estado de una caja

Máquina de estados explícita en `Box.status`:

```
stocked ──(primera venta o rotura)──▶ open ──(huevos restantes = 0)──▶ finished
finished ──(existe la caja siguiente)──▶ ganancia calculable
finished ──(entra en un cierre)──▶ settled
```

- Solo puede haber una caja `open`. Al agotarse, la siguiente `stocked` pasa a `open` automáticamente cuando hace falta.
- La ganancia de una caja solo existe cuando está `finished` y existe la caja siguiente (número + 1): `ganancia = ventas reales − costo de la caja siguiente`. Diferencia y costo final se derivan.
- Huevos restantes = 360 − vendidos − rotos − merma, derivado de los movimientos.

### Tablas

- `partners`: nombre, share (Decimal, la suma de activos = 1), telegram_user_id, activo.
- `exchange_rates`: fecha (única), tasa (Numeric 14,4), fuente (`bcv_api` | `manual`). Si la API falla se usa la última tasa guardada y se dice.
- `purchases`: fecha, proveedor, cantidad de cajas, costo por caja USD, tasa, total USD, total Bs, forma de pago, nota. Siempre la paga el capital.
- `boxes`: número (único, secuencial), purchase_id, costo USD, precios propios (caja, cartón, medio, unidad), status, fechas de apertura y agotamiento, settlement_id.
- `sales`: fecha, tasa, cajas completas, cartones, medios, unidades, monto USD, monto Bs, forma de pago, cliente opcional, nota, anulada (bool + motivo). Una venta nunca se borra, se anula.
- `egg_movements`: el libro del inventario. box_id, fecha, tipo (`sale` | `broken` | `shrinkage` | `gift`), huevos (>0), monto USD (solo ventas), sale_id o count_id. Una venta que cruza dos cajas genera un movimiento por caja; el monto se reparte por huevos y el resto del redondeo va al último movimiento.
- `inventory_counts`: fecha, huevos esperados, huevos contados, diferencia. La diferencia negativa genera un movimiento `shrinkage` en la caja abierta.
- `expenses`: fecha, concepto, monto USD, tasa, monto Bs, pagado por (negocio o socio_id), devuelto_en (fecha o null), settlement_id y si lo devolvió su cierre (`reimbursed_by_settlement`).
- `contributions` (aportes): socio, fecha, monto USD, nota. Llenan el capital y nunca se mezclan con la ganancia.
- `settlements` (cierres): fecha, ganancia de cajas, gastos, reserva, reinversión, ganancia neta, tasa, monto Bs, dinero para la próxima caja, nota. `settlement_shares`: socio, porcentaje, monto.
- `conversation_messages`: chat_id, rol, contenido JSON, fecha. Historial del agente; se mandan los últimos 30.
- `fund_transfers` (movimientos de dinero): fecha, tipo (`between_funds` | `contribution_return` | `profit_withdrawal`), fondo de origen, fondo de destino (solo en un traspaso), socio (solo cuando el dinero sale a un socio), monto, nota, anulado (bool + motivo). La base rechaza una forma imposible (`ck_fund_transfers_shape`): un traspaso tiene destino distinto del origen y no tiene socio; una devolución de aporte sale del capital hacia un socio; un retiro de utilidades sale de cualquier fondo hacia un socio.
- `pending_actions`: un cierre, una anulación o un movimiento de dinero que el modelo preparó y espera el botón Confirmar. chat_id, socio, herramienta, argumentos, vista previa, vence_a, resuelta_a y resultado (`confirmed`, `cancelled`, `superseded`, `expired`, `changed`, `failed`).
- `processed_updates`: update_id de Telegram, para no procesar dos veces un reintento.

### Fondos

El dinero del negocio está en tres fondos. No tienen tabla ni saldo guardado: `app/services/funds.py` arma un diario de asientos (`Posting`: día, fondo, monto con signo, tipo y el cierre que lo hizo) con un `UNION ALL` sobre las filas que ya mueven dinero, así una anulación o una corrección nunca deja un saldo desfasado.

- **Capital**: + aportes − compras no anuladas + en cada cierre el dinero de la próxima caja y la reinversión.
- **Caja chica**: + ventas no anuladas − gastos que pagó el negocio − gastos devueltos a socios (el día de la devolución) − en cada cierre el dinero de la próxima caja, la reinversión, la reserva y las utilidades.
- **Caja de ahorros**: + reservas de los cierres.

Un movimiento entre dos fondos son dos asientos del mismo monto y signo contrario, así la suma de los fondos solo cambia con dinero que entra al negocio o sale de él (aportes, ventas, compras, gastos, devoluciones y utilidades). Dentro de un día, un cierre cuenta después de todo lo demás, y dos cierres del mismo día van en el orden en que se hicieron: `funds.balances(session, Cutoff(día, cierre))` da los saldos justo después de ese cierre, y la vista previa del cierre suma sus asientos planeados (`settlement_postings`) a lo guardado sin escribir nada. `funds.flows` da, por fondo, saldo inicial, entradas, salidas, saldo final y lo movido por tipo de asiento, y es lo que muestra `reports.cash_flow`. `funds.lowest_balance` da el saldo más bajo al final de cada día desde una fecha.

**Movimientos de dinero.** El dinero que no nace de una compra, venta, gasto, aporte o cierre se anota en `fund_transfers` y entra al diario como una rama más: un traspaso entre fondos son dos asientos (sale del origen, entra al destino) y no cambia la suma de los fondos; una devolución de aporte o un retiro de utilidades es un asiento que saca el dinero del negocio. `transfers.move_money` rechaza el movimiento si el fondo de origen queda en negativo algún día desde su fecha, y una devolución de aporte que pase de lo que el socio aportó menos lo que ya se le devolvió. Una devolución de aporte baja lo aportado por ese socio en `funds.balances`; un retiro de utilidades no. Anular un movimiento lo marca anulado y el dinero vuelve solo; se rechaza si el fondo que lo recibió ya lo gastó. No hay edición.

**Sobregiros.** `funds.ensure_covered(session, operación, asientos)` toma el candado del inventario y rechaza con `DomainError` si los asientos planeados dejan en negativo, al final de cualquier día desde su fecha, un fondo del que sacan. El mensaje depende de la operación y, si el día más bajo no es el de la operación, dice qué día quedaría en negativo. La llaman la compra (capital), la devolución a un socio y el cierre (caja chica), y el movimiento de dinero y su anulación (el fondo del que sale). Un gasto y una venta anulada sí pueden dejar la caja chica en negativo: ya pasaron, y rechazarlos no deja anotar la realidad. La vista previa del cierre rechaza igual que el cierre. Un día ya negativo antes de la fecha de la operación no bloquea nada, pero uno posterior sí.

En el resumen de un período, "gastos" es lo que salió de la caja chica: los gastos del negocio y los gastos de socios que se devolvieron en esos días. Los que un socio pagó y al final del período no se le habían devuelto salen aparte, como pendientes de devolver.

### Formas de pago

`PaymentMethod` enum: `efectivo_usd`, `efectivo_bs`, `pago_movil`, `punto`.

## Reglas resueltas (las ambigüedades del cuaderno)

Cada número de este tipo se decidió para que el ejemplo de la Parte 9 dé exacto. Todas las reglas viven en `app/domain/rules.py` y son configurables por variables de entorno donde se indica.

1. **Precios** (amb. 1 y 2). Precio caja = costo × (1 + recargo), recargo 0,25 (`MARKUP`). Cartón y medio: precio caja ÷ 12 y ÷ 24, redondeado hacia arriba al múltiplo de $0,05. Unidad: ÷ 360, hacia arriba al centavo. Comprobado contra 75 → 6,25 / 3,15 / 0,21 y 78,75 → 6,60 / 3,30 / 0,22.
2. **Qué precio se cobra** (amb. 10). Cada caja guarda sus precios, calculados de su propio costo al comprarla, que es lo que hace el ejemplo de la semana. Al comprar una caja más cara, el agente avisa y ofrece subir los precios de la caja abierta (herramienta `ajustar_precios`). Los precios también se pueden fijar a mano.
3. **Bolívares** (amb. 3 y 4). Bs = USD × tasa, redondeado al centavo con medio hacia arriba. USD desde Bs = Bs ÷ tasa al centavo.
4. **Rotos** (amb. 6). Se registran como movimiento `broken` de la caja abierta y no se cobran. La hoja de la caja muestra "huevos" = vendidos + rotos, y debe dar 360.
5. **Reparto** (amb. 5). Cada parte se calcula al centavo con medio hacia arriba; si la suma no da exacto, el centavo de diferencia se ajusta en el socio de mayor porcentaje. 9,52 → 5,71 / 3,81.
6. **Gastos del cierre** (amb. 11). Un cierre toma todos los gastos sin cierre con fecha hasta la del cierre, sin importar a qué caja se refieran.
7. **Reserva y reinversión** (amb. 12). Las dos son opcionales y se pasan al cierre en USD o en porcentaje; el porcentaje es sobre (ganancia de cajas − gastos). La reserva va a la caja de ahorros y la reinversión al capital. Juntas no pueden pasar de esa ganancia: el cierre se rechaza.
8. **Cierre sin cajas** (amb. 11). Se permite: ganancia de cajas 0, resta los gastos y la ganancia neta puede salir negativa. Una ganancia neta negativa no se reparte: el cierre queda registrado con partes en 0 y los gastos quedan cubiertos por la caja chica.
9. **Devolución al socio** (Parte 7). Un gasto pagado por un socio queda pendiente de devolución. Se devuelve completo, nunca una parte: a mano antes del cierre (`expenses.reimburse`, uno o varios gastos, o todo lo que se le debe a un socio con `reimburse_partner`) o en el cierre, que devuelve los que sigan pendientes en su fecha y lo deja anotado en el gasto. Solo `expenses.reimburse` escribe la devolución, bajo el candado del inventario, y la rechaza sin guardar nada si el gasto no existe, lo pagó el negocio, ya se devolvió, la fecha es futura, es anterior al gasto o es anterior al día del último cierre. El gasto baja la ganancia del cierre aunque se haya devuelto antes: quién adelantó el dinero es una cuestión de caja, no de ganancia. Un cierre con fecha futura se rechaza.
10. **Merma de conteo** (amb. 16). Se carga a la caja abierta (o a la más vieja con huevos) como `shrinkage`.
11. **Costo promedio** (amb. 15). Se calcula sobre las cajas con huevos: valor de cada caja = costo × huevos restantes ÷ 360. Promedio por caja = valor total ÷ (huevos totales ÷ 360). Es solo informativo.
12. **Costos unitarios** (amb. 17). Se guardan sin redondear y se muestran con 4 decimales.
13. **Tasa del día**. Siempre la del día de la operación. Si no hay, se busca en la API y se guarda. Una operación con fecha pasada usa la tasa guardada de esa fecha o la última anterior.
14. **Compras desde el capital** (amb. 13). Toda compra la paga el capital; un socio no paga cajas. Si el capital no alcanza, la compra se rechaza diciendo cuánto falta aportar. Una compra con fecha pasada se revisa contra el saldo más bajo de cada día desde su fecha hasta hoy, no solo contra el de hoy. La revisión (`funds.ensure_covered`) corre bajo el mismo candado del inventario que la compra, así dos compras a la vez no pasan las dos. Las compras que un socio había pagado antes de este cambio se pasaron a aportes suyos en la migración `3e5b9a7c4d12`.
15. **Destino del dinero en el cierre** (Parte 8). Primero vuelve al capital el costo de reponer las cajas cerradas (el dinero de la próxima caja). Los gastos y devoluciones siguen como antes. De la ganancia que queda salen la reinversión (al capital) y la reserva (a la caja de ahorros); el resto son las utilidades de los socios, que salen del negocio el mismo día del cierre. La vista previa muestra cómo quedan caja chica, capital y ahorros justo después del cierre. Si la caja chica no alcanza para todo lo que el cierre saca, el cierre se rechaza diciendo cuánto falta.

## Servicios

`app/services/` guarda toda la lógica. FastAPI y el agente llaman a las mismas funciones. Cada función recibe la sesión de base de datos, valida y devuelve un modelo Pydantic. Los errores del negocio son `DomainError` con un mensaje en español para el usuario.

- `rates`: obtener o crear la tasa de un día; fijarla a mano.
- `purchases`: registrar compra (crea cajas con precios), anular compra si ninguna caja se tocó.
- `sales`: registrar venta (cajas, cartones, medios, unidades, forma de pago, fecha opcional, monto cobrado opcional para descuentos), reparte en cajas PEPS, rechaza si no hay huevos. Anular venta.
- `inventory`: registrar rotos o regalados, conteo físico, existencias (huevos, cajas, por caja), costo promedio.
- `expenses`: registrar gasto (en $ o en Bs; los Bs se pasan a $ con la tasa del día), devolver gastos a un socio (uno, varios o todos los suyos), listar pendientes.
- `pricing`: lista de precios del día en USD y Bs (Plantilla A), ajustar precios de una caja.
- `boxes`: hoja de una caja (Plantilla C) y su ganancia (Plantilla G).
- `settlements`: vista previa del cierre (Plantilla H) y ejecutar el cierre.
- `contributions`: registrar aporte, listar.
- `funds`: el diario de asientos; saldos de capital, caja chica y caja de ahorros, y aportes por socio; movimientos de un período; la regla de sobregiros.
- `transfers`: mover dinero entre fondos o hacia un socio (devolución de aporte, retiro de utilidades), anularlo y listarlo.
- `reports`: resumen de un período (ventas, compras, gastos, ganancia, por forma de pago) y el dinero de cada fondo en el período.

## API REST

`/api/v1/...` con un router por servicio. Todo con `X-API-Key` salvo `/healthz` y `/telegram/webhook`. Sirve de respaldo y para integraciones; la interfaz principal es Telegram.

## Agente

El modelo elige herramientas y llena campos; toda cuenta la hace el código. Las decisiones y sus fuentes están en `docs/investigacion-haiku.md`.

- **Herramientas** (`app/agent/tools.py`): 15, en una tabla `Tool(nombre, descripción, modelo de entrada, handler, tipo, ejemplos)` con un solo despachador. Tipos: lectura, escritura y confirmación. Escrituras: `registrar_venta`, `registrar_compra`, `registrar_gasto`, `registrar_merma`, `registrar_conteo`, `registrar_aporte`, `fijar_tasa`, `ajustar_precios`, `marcar_gasto_devuelto` (un gasto, o con `socio` todo lo que se le debe). Confirmación: `preparar_cierre`, `preparar_anulacion` (venta, compra o movimiento de dinero), `mover_dinero` (traspaso, devolver aporte o retirar utilidades). Lecturas: `consultar` (un `enum` de qué mostrar), `ver_caja`, `resumen`.
- **Esquemas planos y strict.** Cada herramienta tiene su modelo de entrada en la frontera, con nombres de campo en español como hablan los socios (cartones, medios, sueltos, pagado_por) y separado de los modelos de los servicios. Todo campo es un escalar o un `enum`: sin `$ref`, sin `anyOf`, sin objetos anidados. El dinero es un string con `pattern` que acepta coma o punto decimal y se convierte a `Decimal` en el código. Los opcionales tienen valor por defecto en vez de `null`. El generador quita `minimum`, `maxLength` y parecidos (strict los rechaza; Pydantic los sigue validando) y se niega a generar algo anidado. Todas van con `strict: true` y las de escritura con `input_examples`. Un test verifica que el conjunto cabe en los límites de strict (20 herramientas, 24 opcionales, 16 uniones).
- **Valores que resuelve el código.** `forma_pago` y `pagado_por` aceptan `no_dijo`, que el despachador rechaza pidiendo que se pregunte: con strict el modelo siempre llena el campo, y así no tiene que inventar. `yo` en `pagado_por` o `socio` es quien escribe. Cajas, cartones, medios y sueltos van en campos enteros separados y el código los multiplica. Un nombre de herramienta con otra capitalización se acepta; uno desconocido devuelve la lista de nombres.
- **Confirmación con botones.** `preparar_cierre`, `preparar_anulacion` y `mover_dinero` ejecutan la operación dentro de una transacción que se deshace, guardan argumentos y resultado como acción pendiente y devuelven la vista previa. El bot pone Confirmar y Cancelar (inline keyboard de Telegram, `CallbackQueryHandler`) debajo de la respuesta. Confirmar vuelve a ejecutar el mismo handler, ahora de verdad, solo si: lo toca el socio que la pidió, no se usó antes (se toma con `SELECT ... FOR UPDATE`), no venció (15 minutos), no la reemplazó una vista previa más nueva del mismo chat y el resultado es igual a la vista previa (si cambió algo, se rechaza). Después el modelo recibe una nota "[Botón Confirmar]" con el resultado para contarlo y seguir.
- **System prompt** (`app/agent/prompt.py`): secciones XML (`negocio`, `como_trabajar`, `confirmaciones`, `como_hablar`, `ejemplos`) con ocho ejemplos de frase → llamada, varios con palabras venezolanas. La fecha (también en ISO), el lunes de la semana, la tasa y quién escribe van en el mensaje del usuario, no en el system, para no romper el cache.
- **Thinking y esfuerzo** (`app/agent/options.py`): cada request manda `thinking` y `output_config.effort`. Por defecto *adaptive* con esfuerzo `medium` en Haiku 5.5 y Sonnet 5.5. `ANTHROPIC_EFFORT` y `ANTHROPIC_THINKING` lo cambian; `off` es `disabled` en Haiku y `between_tools` en Sonnet 5.5, y se rechaza al arrancar por encima de `high`. `tool_choice` queda en `auto`.
- **Bucle**: hasta 10 rondas de tool use; cada resultado vuelve como JSON. Un `DomainError` o datos inválidos vuelven como `is_error`. Un `stop_reason` de `refusal` tiene su propia respuesta.
- El historial se guarda por chat. Comando `/nuevo` lo borra. Comando `/start` saluda.
- Las respuestas largas se parten en mensajes de 4096 caracteres; los botones van en el último.

## Pruebas

pytest + pytest-asyncio contra un Postgres real (docker compose, puerto 5432). La prueba principal reproduce la semana completa de la Parte 9 y verifica cada número: ventas por día, 360 huevos, ventas de la caja 1 = 74,42, ganancia 11,42, gastos 1,90, neta 9,52, socios 5,71 y 3,81. Las reglas de redondeo se prueban contra los ejemplos de las Partes 3, 4 y 6. El agente se prueba con un cliente de Anthropic falso que pide herramientas, para verificar el despacho, el bucle y los botones sin red.

El eval del producto está en `evals/`: 62 casos en `casos.yaml` que arrancan de fixtures construidos con los servicios, se corren contra la API real con `uv run python -m evals.run` y se califican sin modelo (llamadas, estado de la base, palabras de la respuesta). `--golden` y `tests/test_evals.py` corren todos los casos con un cliente guionado: prueban el programa y que el estado esperado de cada caso sale de sus llamadas esperadas.

## Decisiones de implementación

Puntos que el diseño dejaba abiertos y cómo quedaron en el código.

- **Precio de una venta que cruza cajas.** Se cobra con los precios de la caja donde empieza (la abierta). El monto se reparte entre las cajas por huevos, con el resto del redondeo en la última. En la hoja de la caja, los Bs de esa venta se reparten en la misma proporción que los dólares.
- **Anular una venta.** Se borran sus movimientos y cada caja vuelve al estado que dicen sus movimientos restantes. Por eso la máquina de estados también permite `finished → open`, `finished → stocked` y `open → stocked`. Se rechaza si alguna caja ya está `settled`, o si el resultado rompe el orden PEPS (dos cajas abiertas, o una caja vieja con huevos detrás de una más nueva ya empezada).
- **Anular una compra.** Solo si todas sus cajas siguen `stocked`. Sus cajas se borran y las cajas posteriores se renumeran hacia abajo, para que "la caja siguiente" siga siendo número + 1.
- **Conteo con más huevos de los anotados.** Se guarda el conteo con su diferencia positiva y un aviso, pero no se agregan huevos al inventario.
- **Cierre vacío.** Si no hay cajas cerrables ni gastos pendientes, el cierre se rechaza.
- **Historial del agente.** Se guardan los mensajes sin los bloques de *thinking*: la ventana de 30 mensajes recorta el principio del historial, y la API invalida un bloque de *thinking* cuando cambia lo que va antes de él. Dentro de una misma respuesta los bloques sí se devuelven tal cual.
- **Telegram que no arranca.** Si Telegram rechaza el token o no responde al iniciar, se registra el error y la API sigue funcionando con el bot apagado.
- **Campos de las herramientas.** Al principio los esquemas salían de los modelos de entrada de los servicios, en inglés, y la confirmación era un campo `confirmado`. Se cambió por modelos propios del agente en español y por botones (ver Agente): 28 herramientas no cabían en el límite de strict, los esquemas de Pydantic traían `anyOf` y `minimum` que strict rechaza, y un cierre no debe depender de que el modelo lea bien un "sí".
- **Caja completa.** Una venta puede llevar cajas completas, cobradas al precio de caja. Antes una caja se anotaba como 12 cartones, que con el redondeo hacia arriba cuesta más ($ 79,20 contra $ 78,75 en una caja de 63).
- **Hoy en los evals.** `today()` se puede fijar por contexto (`frozen_today`) para que los fixtures del eval repitan las fechas de la Parte 9; en producción no se usa.
