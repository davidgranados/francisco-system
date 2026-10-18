# Cómo se despliega

Hay dos entornos en Railway, con dos caminos distintos:

| Entorno | Cuándo se despliega | Cómo |
|---|---|---|
| `staging` | En cada push a `main`, solo | Railway está conectado al repositorio, rama `main` |
| `production` | Solo cuando alguien publica un release en GitHub | El workflow `.github/workflows/prod-deployment.yml` corre las pruebas sobre el tag y sube ese código con `railway up` |

Producción **no** está conectada al repositorio. Hacer merge o push a `main` nunca la toca. Publicar un release sí: publicar un release **es** desplegar a producción.

## Flujo normal

1. Se trabaja en una rama y se abre un PR. `ci.yml` corre lint, la revisión de migraciones y las pruebas.
2. Se hace merge a `main`. Staging se despliega en segundos con su propia base de datos y su propio bot.
3. Se prueba en staging, con el bot de staging y los usuarios de desarrollo.
4. Cuando está bien, se publica un release desde `main`:

   ```bash
   gh release create v0.2.0 --target main --generate-notes
   ```

   O en GitHub: **Releases → Draft a new release**, tag nuevo `v0.2.0`, target `main`, **Publish release**.
5. El workflow corre CI sobre el tag y, si pasa, despliega ese tag a producción. Railway corre `alembic upgrade head` antes de arrancar la versión nueva.

Si el CI o el despliegue fallan, el workflow borra el release y el tag. Que el tag no exista quiere decir que falló, no que nadie lo intentó.

## Hotfix

Un arreglo urgente que no puede esperar lo que ya está en `main` sale de una rama `hotfix/vX.Y.Z` creada desde el último tag:

```bash
git checkout -b hotfix/v0.2.1 v0.2.0
# arreglo, commit, push
gh release create v0.2.1 --target hotfix/v0.2.1 --generate-notes
```

Después, el arreglo se lleva también a `main` con un PR. El workflow solo acepta releases cuyo target sea `main` o `hotfix/v*`; uno publicado desde otra rama no hace nada.

## Saber qué hay en producción

El último release publicado que no se borró:

```bash
gh release list --limit 5
```

## Cuidado con las migraciones

Las migraciones corren antes de que arranque la versión nueva. Volver al tag anterior **no** deshace el cambio de la base de datos. Escriba migraciones con las que la versión anterior siga funcionando.

## Configuración (una sola vez)

En Railway:

1. **Desconectar producción del repositorio.** Proyecto → entorno `production` → servicio `francisco-system` → **Settings → Source → Disconnect**.
2. **Staging conectado a `main`.** Entorno `staging` → servicio `francisco-system` → **Settings → Source**: repositorio `davidgranados/francisco-system`, rama `main`.
3. **Token de despliegue.** Proyecto → **Settings → Tokens** → crear un token para el entorno `production`. Es un *project token*: solo sirve para desplegar en ese entorno.

En GitHub, repositorio → **Settings → Secrets and variables → Actions**:

| Tipo | Nombre | Valor |
|---|---|---|
| Secret | `RAILWAY_PRODUCTION_TOKEN` | el token del paso 3 |
| Variable | `RAILWAY_SERVICE` | `francisco-system` |

## Fuentes

- Railway, desplegar con la CLI y project tokens: <https://docs.railway.com/cli/deploying>
- Railway, entornos: <https://docs.railway.com/environments>
- GitHub Actions, evento `release`: <https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#release>
