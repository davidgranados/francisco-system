# Guía: crear el bot de Telegram y conectarlo a la app

Esta guía lleva de cero a un bot que contesta a los socios. Son unos 15 minutos. Hace falta:

- Telegram en el teléfono o en la computadora.
- Acceso al proyecto de Railway donde corre la app (servicio `francisco-system`).
- La [CLI de Railway](https://docs.railway.com/guides/cli) instalada, para cargar los socios.

Cómo funciona por dentro: la app no "pregunta" a Telegram si hay mensajes. Al arrancar, le dice a Telegram "mándame cada mensaje a `https://<dominio>/telegram/webhook`" (eso es el *webhook*), junto con una contraseña que Telegram repite en cada envío. La app descarta todo lo que llegue sin esa contraseña y solo contesta a quien esté registrado como socio.

## Paso 1. Crear el bot con BotFather

1. En Telegram, busque **@BotFather** (tiene la marca azul de verificado) o abra <https://t.me/BotFather>.
2. Mande `/newbot`.
3. Le pide el **nombre** que se ve en el chat. Por ejemplo: `Cuentas Huevos`.
4. Le pide el **usuario**, que debe terminar en `bot` y no puede estar tomado. Por ejemplo: `cuentas_huevos_bot`.
5. BotFather responde con el **token**, algo como `7123456789:AAH...`. Cópielo.

> El token es la llave del bot: quien lo tenga puede hacerse pasar por él. No lo mande por chat, no lo ponga en el código ni en capturas de pantalla. Si se filtra, en BotFather use `/revoke`, elija el bot y ponga el token nuevo en Railway (paso 3).

## Paso 2. Ajustar el bot (opcional, recomendado)

Todo esto se hace en BotFather con `/mybots` → elija el bot → **Edit Bot** / **Bot Settings**.

| Qué | Dónde | Valor |
|---|---|---|
| Comandos del menú | **Edit Commands** (o `/setcommands`) | ver abajo |
| Descripción | **Edit Description** | `Asistente de las cuentas del negocio de huevos. Solo para los socios.` |
| Grupos | **Bot Settings → Allow Groups?** (o `/setjoingroups`) | **Turn groups off** |

Lista de comandos para pegar cuando BotFather la pida:

```
start - Saludo y cómo usar el bot
nuevo - Empezar la conversación desde cero
```

Por qué apagar los grupos: el bot está pensado para chats privados con cada socio. Si alguien lo agrega a un grupo, contestaría ahí a los mensajes de los socios, a la vista de todos.

## Paso 3. Poner las variables en Railway

En [railway.com](https://railway.com), abra el proyecto → servicio **francisco-system** → pestaña **Variables**.

### 3.1 `TELEGRAM_BOT_TOKEN`

**New Variable** → nombre `TELEGRAM_BOT_TOKEN`, valor: el token del paso 1.

### 3.2 `TELEGRAM_WEBHOOK_SECRET`

Ya existe en el servicio, pero conviene revisarlo: abra la variable y mire el valor.

- Si es una cadena larga al azar (por ejemplo `kJ3x_9Qp-...`), déjela.
- Si se ve literalmente como `${{ secret(...) }}`, o tiene espacios u otros símbolos, reemplácelo. Telegram solo acepta letras, números, `_` y `-`, de 1 a 256 caracteres.

Para generar uno nuevo en su computadora:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

No hace falta copiarlo a ningún otro lado: la app se lo pasa a Telegram sola al arrancar.

### 3.3 Revisar las demás

| Variable | Debe tener |
|---|---|
| `PUBLIC_URL` | `https://francisco-system-production.up.railway.app`, sin barra al final |
| `ANTHROPIC_API_KEY` | la clave de Anthropic (ya está puesta) |
| `ANTHROPIC_MODEL` | el modelo del agente, por ejemplo `claude-sonnet-5-5` |

### 3.4 Desplegar

Railway junta los cambios de variables y muestra un aviso arriba (**Apply changes** / **Deploy**). Haga clic para aplicarlos: la app se vuelve a desplegar y, al arrancar, registra el webhook en Telegram.

## Paso 4. Saber el id de Telegram de cada socio

El bot reconoce a los socios por su número de usuario de Telegram, no por el nombre ni el teléfono.

Cada socio, desde su cuenta, le escribe a **@userinfobot** (<https://t.me/userinfobot>) cualquier cosa. Responde con un `Id`, un número como `123456789`. Anótelo.

## Paso 5. Cargar los socios en la app

Desde una terminal con la CLI de Railway:

```bash
railway login
railway link          # elija el proyecto y el servicio francisco-system
railway ssh
```

Ya dentro del servicio:

```bash
python -m app.seed "Francisco:0.60:123456789" "Socio B:0.40:987654321"
```

Cada socio va como `Nombre:porcentaje:id_de_telegram`. Las reglas:

- Los porcentajes van en decimales y deben sumar 1 (`0.60` + `0.40`).
- La lista es completa: un socio que no aparezca queda inactivo.
- Correrlo dos veces con lo mismo no cambia nada, así que se puede repetir sin miedo.

Debe imprimir una línea por socio, con su porcentaje y su id.

## Paso 6. Probar

1. **La app está arriba**: abra <https://francisco-system-production.up.railway.app/healthz>. Debe decir `{"status":"ok"}`.
2. **Telegram tiene el webhook**: en el navegador, abra

   ```
   https://api.telegram.org/bot<TOKEN>/getWebhookInfo
   ```

   cambiando `<TOKEN>` por el token completo. Revise:
   - `url` = `https://francisco-system-production.up.railway.app/telegram/webhook`
   - `pending_update_count` en `0` o bajando
   - `last_error_message` vacío o ausente

   (Esa dirección lleva el token: no la comparta ni la deje en el historial de una computadora ajena.)
3. **El bot contesta**: desde la cuenta de un socio, abra el bot (`https://t.me/<usuario_del_bot>`) y mande `/start`. Debe saludar por el nombre.
4. **El agente trabaja**: pregúntele "¿cuál es la tasa de hoy?" o "¿cuántos huevos quedan?".
5. **Un extraño no entra**: desde una cuenta que no sea socio, mande `/start`. El bot no debe contestar nada.

## Usuarios de desarrollo

Para que una persona del equipo técnico pruebe el bot sin ser socio, ponga en Railway la variable `DEV_TELEGRAM_USERS` con pares `nombre:id_de_telegram` separados por comas, por ejemplo `David:820460532,Otro:123`, y vuelva a desplegar. El id se saca con @userinfobot, como en el paso 4.

- Pueden hacer todo lo que hace un socio (registrar, consultar, preparar y confirmar cierres y anulaciones con los botones), pero no tienen porcentaje y no entran en el reparto.
- "Yo" no es ningún socio para ellos: si dicen "pagué yo", el bot les pregunta qué socio fue.
- Si el id coincide con el de un socio activo, se trata como ese socio.
- Úselos en el ambiente de staging, no en producción: sus ventas de prueba entran en las cuentas reales.

## Si algo falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| El bot no contesta a nadie y `getWebhookInfo` tiene `url` vacía | La app no arrancó el bot | En Railway → **Deployments** → **View logs**. Si dice `Telegram is disabled`, falta una de las dos variables del paso 3. Si dice `Telegram failed to start`, el token está mal: cópielo de nuevo de BotFather |
| `last_error_message`: `Wrong response from the webhook: 403 Forbidden` | El secreto que tiene Telegram no es el de la app | Vuelva a desplegar la app (paso 3.4): al arrancar, registra el secreto actual |
| `last_error_message`: `404 Not Found` | La app está arriba pero sin bot | Mismo caso que la primera fila: revise los logs |
| `last_error_message` con un error de conexión o de SSL | `PUBLIC_URL` está mal | Debe empezar con `https://` y ser el dominio del servicio, sin barra final |
| `getWebhookInfo` contesta `Unauthorized` | El token está mal o fue revocado | Copie el token actual de BotFather |
| El bot saluda pero no contesta los mensajes | No es un problema de Telegram | Los logs dirán `agent failed`; revise `ANTHROPIC_API_KEY` y `ANTHROPIC_MODEL` |
| Contesta "El asistente no está configurado todavía" | Falta `ANTHROPIC_API_KEY` | Póngala en Railway y despliegue |
| Un usuario de desarrollo no contesta, o la app no arranca | `DEV_TELEGRAM_USERS` mal escrita (debe ser `nombre:id,nombre:id`, sin repetidos) | Revise los logs y corrija la variable |
| A un socio no le contesta y al otro sí | Su id no está cargado o está mal | Revise su id con @userinfobot y repita el paso 5 con la lista completa |

> Ojo con los logs: si Telegram rechaza el token al arrancar, el mensaje de error puede mostrar el token. Si se lo muestra a alguien, revóquelo con `/revoke`.

## Fuentes

- Telegram Bot API, `setWebhook`, `getWebhookInfo` y `deleteWebhook`: <https://core.telegram.org/bots/api#setwebhook>
- Funciones de los bots, BotFather y revocar el token: <https://core.telegram.org/bots/features#botfather>
- Tutorial oficial, de BotFather al primer mensaje: <https://core.telegram.org/bots/tutorial>
- Comandos de bot: <https://core.telegram.org/api/bots/commands>
