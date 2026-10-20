# Code Comments: None by Default, One Line When Needed, Never the Whole Story

## Rule

Code does not carry comments by default. Names, types and tests are what
explain it. A comment is allowed only when the code cannot say it, and then it
is **one line, in English**, and it is one of these two things:

1. **The non-obvious why.** A reason a reader cannot recover from the code: a
   constraint from outside (Telegram, the BCV rate, Anthropic's API, Railway),
   an invariant another module depends on, a trap that looks like a bug but is
   not.
2. **A pointer.** Where the full reasoning lives:
   `# See docs/diseno.md, "Fondos"`, `# See docs/despliegue.md`.

The long reasoning (history, alternatives, who decided, what broke before)
goes to the place built for it, never into the source file:

| Kind of explanation | Where it goes |
|---|---|
| Why the design is this way, alternatives weighed | `docs/diseno.md` |
| How it is deployed and operated | `docs/despliegue.md`, `README.md` |
| What this change does and what to watch in review | PR description |
| Why a line changed | Commit message |

This applies the same way to **docstrings**: a short summary of what the
function does and returns, not an essay.

Spanish is never used in a comment or docstring
(`.claude/rules/code-in-english-spanish-only-facing-the-user.md`). The one
place a `#` line is Spanish is `evals/casos.yaml`, which is a document the
partners can read, not code.

## ❌ Don't

```python
# Antes redondeábamos cada porcentaje por separado y la suma pasaba por un
# centavo, lo que descuadraba la liquidación de la Parte 9. Probamos
# redondear al final pero el socio veía montos distintos en Telegram...
reinvestment = total - sum(shares)
```

Three lines, in Spanish, telling a bug's history inside a calculation.

```python
async def record_sale(session, sale):
    """Record a sale.

    First we look up the rate, and if there is none for that day we take the
    previous one, because the BCV does not publish on weekends, and then we
    price the boxes, cartons, halves and units, and then ...
    """
```

A walkthrough of the body living in a docstring.

## ✅ Do

```python
# Two percents rounded apart can overshoot by a cent; the reinvestment absorbs it.
reinvestment = total - sum(shares)
```

```python
async def record_sale(session, sale):
    """Record a sale priced at the day's rate, or the latest one before it."""
```

## Before writing a comment, ask

1. Would a better name, a smaller function or a test say this instead? Then do that.
2. Does it explain *why*, and is that why invisible from the code? If it explains *what*, delete it.
3. Does it fit in one line? If not, write it in `docs/` and leave a pointer.

## Existing comments

The banner lines in `app/agent/tools.py` (`# --- Writes ---`) are section
markers in a long registry, not explanations; leave them. When you touch a
function, bring its comments to this rule. Do not match the comment density
around you.

## Why this rule exists

Adapted from firu's rule of the same name, set by David Granados on
2026-09-14, after comments there grew to thousands of lines, many in Spanish.
Agents copy the comment density of the file they edit, so the rule has to
exist before the long comments do. A comment that tells a history ages badly:
the code changes, the comment does not, and the next reader trusts the wrong
one.
