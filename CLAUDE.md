# CLAUDE.md

- Publishing a GitHub release deploys to production (`.github/workflows/prod-deployment.yml`). Never create, publish or edit a release, or push a `v*` tag, unless a person asked for a production deploy in those words. Pushing to `main` deploys staging only. See `docs/despliegue.md`.
- Code and identifiers in English; text people read (bot replies, docs, error messages) in Spanish.
