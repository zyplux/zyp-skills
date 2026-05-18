# Naming conventions (Python and TypeScript)

These rules describe **which words to pick** for names — not how to case them. Apply your target language's idiomatic casing on top. Examples are written as space-separated word phrases so they read the same in either language.

## General principles

- **Optimise for the reader.** A clear long name beats a clever short one. Prefer `get initials` over `gi`. Code is read far more often than written.

- **Match the vocabulary of the domain.** Use the words the product, users, or external API already use. If the domain says "customer," don't call it "client." A shared glossary prevents drift.

- **Don't encode the type in the name.** Type systems and annotations already carry that information. Drop suffixes like `array`, `str`, `int`, `bool`, `dict` — they're redundant.

- **Avoid placeholder words.** `data`, `info`, `process`, `handle`, `manage`, `value`, `object`, `item`, `thing`, `stuff` carry no meaning. Replace each with what the thing actually is.

- **Spell names out; don't truncate by deleting letters.** `configuration` or `config` (an accepted abbreviation), never `cfg`, `usr`, `prc`. Single letters are reserved for conventional tight scopes — `i`/`j`/`k` for loop indices, `x`/`y` for coordinates. Avoid `l`, `O`, and `I` as standalone names since they look like digits.

- **Cut filler.** Drop `use`, `with`, `do`, `perform`, `handle`, `helper`, `util`, `manager` unless they distinguish a sibling. The action verb or domain noun alone usually carries the meaning.

## Functions and methods

- **Start with a verb that names the action.** Prefer `calculate total` over `total`, `save user` over `user saver`. A function is an action; the name should make that obvious without reading the body.

- **Pick the verb that matches the cost and side effects.** Establish a consistent verb vocabulary and apply it across the codebase. Don't mix `get users` and `list users` for the same operation:

  | Verb | Use for |
  |---|---|
  | `get` | Cheap, in-memory, single-item lookup that always succeeds |
  | `find` | Predicate search that may return nothing |
  | `list` | Return a collection (often after a scan or filter) |
  | `fetch` | Network I/O |
  | `load` | Disk or cache read |
  | `compute` / `calculate` | Non-trivial derivation |
  | `build` / `make` | Construct a new value or object |
  | `parse` | String → structured value |
  | `serialize` / `format` | Structured value → string |
  | `validate` | Check invariants; raise or return an error on failure |
  | `ensure` | Make a condition true (idempotent) |

- **Boolean-returning functions read as questions.** Prefix with `is`, `has`, `can`, `should`, or `was`. Prefer positive phrasing (`has value`) over negated (`is not empty`); negations compound badly at call sites.

- **Reserve property-style access for cheap, pure reads.** Python `@property` and TypeScript `get`/`set` accessors must not do I/O, must not mutate observable state, and should return the same value on repeated calls (a one-time cached computation is fine). If it can fail, block, or surprise — make it a method.

## Variables and parameters

- **Use a noun that describes what the value holds, not how it's stored.** Prefer `original image` over `img1`, `user email` over `str`.

- **Plural for collections, singular for items.** A list of users is `users`; one element pulled from it is `user`. The plural already carries cardinality — don't append `list`, `array`, or `collection`.

- **Don't restate the containing context.** Inside a user class, the field is `email`, not `user email`. Inside an image class, the field is `width`, not `image width`. The enclosing scope already qualifies the name.

## Classes, types, and interfaces

- **Use nouns or noun phrases for what the thing represents.** A class is a thing, not an action; prefer `order processor` over `process order`.

- **Don't mark types with typographic prefixes or suffixes.** No `I` prefix on interfaces, no `T` prefix on types, no `Type`/`Interface`/`Impl` suffixes. Name the concept (`user`, `todo item storage`) and distinguish implementations by purpose, not by marker.

- **Suffix error and exception classes with `Error`.** A parse failure is a `parse address Error`, not a `parse address Failure` or `parse address Exception`. The `Error` suffix is the visual cue.

- **Use a consistent word order across related names.** If one error reads as verb-object-`Error`, every sibling should too. Don't mix `parse address Error` with `lookup Error dns` — pick the ordering that fits the domain and apply it uniformly to the whole family.

## Constants

- **Name the concept, not the literal value.** `max retry attempts` describes intent; `three` describes nothing. The name should still read correctly if the underlying number changes.
