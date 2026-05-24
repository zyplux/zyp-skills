---
title: PyTS Naming Conventions
---

## Naming Conventions

Every name answers: what does it *hold*, *do*, or *represent*? Use domain words. No filler, no type tag, no scope echo.

Apply the language's idiomatic casing on top of these rules.

- Spell names out; long-and-clear over short-and-clever. Mirror domain vocabulary.
- Drop type suffixes (`array`/`str`/`int`/`bool`/`dict`).
- Replace placeholder nouns (`data`/`info`/`value`/`item`/`result`/`output`) with what it actually is.
- Replace filler verbs (`process`/`handle`/`do`/`perform`/`execute`/`manage`) with what the function actually does.
- Start every function name with a verb; pick one verb per semantic and stay consistent across the codebase. Match cost and intent — examples:
  - reads: `get` cheap in-memory · `find` may miss · `list` collection · `fetch` network · `load` disk/cache · `calc` non-trivial derivation
  - shape: `parse` string → structured value · `serialize`/`format` structured value → string · `build`/`make` construct new value
  - writes: `save` persist · `create` new entity · `delete` remove · `ensure` make condition true (idempotent)
  - checks: `validate` check invariants (raises on failure)
- Name variables by what they hold, not how they're stored (`original image`, not `img1`); pluralise collections, singularise items.
- Drop scope echoes — inside `User`, the field is `email`, not `user email`.
- Phrase booleans as questions (`is`/`has`/`can`/`should`); prefer positive (`has value` over `is not empty`).
- Keep properties (`@property`, TS `get`/`set`) cheap and pure — no I/O or mutation; otherwise make it a method.
- Name constants by concept, not literal (`MAX_RETRY_ATTEMPTS`, never `THREE`).
- Use noun phrases for classes and types (`order processor`, not `process order`); no `T` prefix or `Type`/`Impl` suffix.
- End error classes with `Error` (`parse address Error`); keep one word order across siblings.
