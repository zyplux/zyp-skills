# Naming conventions (Python and TypeScript) — short

Rules pick the **words**; apply the target language's idiomatic casing on top. Examples are space-separated so they read the same in either language.

## General

- **Optimise for the reader.** Clear-and-long beats clever-and-short.
- **Use domain vocabulary.** Mirror the words the product, users.
- **Don't encode the type.** Drop `array`/`str`/`int`/`bool`/`dict`/`collection` suffixes.
- **No placeholder words.** Replace `data`/`info`/`process`/`handle`/`value`/`object`/`item`/`thing` with what it actually is.
- **Cut filler.** Drop `use`/`with`/`do`/`perform`/`handle`/`helper`/`util`/`manager` unless they distinguish a sibling.

## Functions and methods

- **Start with a verb.** Prefer `calc total` over `total`.
- **Match the verb to cost and side effects** — and use one verb per semantic across the codebase:

  | Verb | Use for |
  |---|---|
  | `get` | Cheap in-memory single-item lookup that always succeeds |
  | `find` | Predicate search that may return nothing |
  | `list` | Return a collection |
  | `fetch` | Network I/O |
  | `load` | Disk or cache read |
  | `calc` | Non-trivial derivation |
  | `build` / `make` | Construct a new value |
  | `parse` | String → structured value |
  | `serialize` / `format` | Structured value → string |
  | `validate` | Check invariants; error on failure |
  | `ensure` | Make a condition true (idempotent) |

- **Booleans read as questions.** Prefix `is`/`has`/`can`/`should`/`was`, prefer positive (`has value`) over negated (`is not empty`).
- **Property access stays cheap and pure.** Python `@property` and TS `get`/`set` must not do I/O, mutate, or surprise — otherwise make it a method.

## Variables and parameters

- **Noun for what it holds, not how it's stored.** `original image`, not `img1`.
- **Plural for collections, singular for items**.
- **Don't restate the enclosing scope.** Inside a user class the field is `email`, not `user email`.

## Classes, types

- **Noun phrases, not actions.** `order processor`, not `process order`.
- **No typographic markers.** No `T` prefix, no `Type`/`Impl` suffix.
- **Errors end in `Error`.** `parse address Error`, not `parse address Failure`/`Exception`.
- **One word order across siblings.** Pick e.g. verb-object-`Error` and apply it to the whole family.

## Constants

- **Name the concept, not the value.** `MAX_RETRY_ATTEMPTS`, not `THREE`.
