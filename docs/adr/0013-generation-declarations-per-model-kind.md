# ADR 0013: Generation declarations are per (model, kind) rows resolved by one module

## Status

Accepted — 2026-09-15. Supersedes the storage half of ADR 0012 (its decision 2 and the
delete-leaves-dangling consequence); the catalogue and the named profiles of ADR 0012 stand.

## Context

ADR 0012 gave a model row a single `generation_capability_ref` string. Shipping it surfaced four
structural problems:

- **One ref cannot serve two kinds.** A model row can carry both `image` and `video` capability,
  but sizes, durations and source roles share no defaults across kinds, so a dual-capability model
  could only be configured for whichever kind the UI happened to pick first.
- **`profile:<id>` is a string, not a reference.** Nothing in the database kept it valid, and
  deleting a custom profile left pointing rows with a dangling id whose name and content were both
  gone. ADR 0012 accepted that as "the user can still see what they had configured" — in practice
  what the user sees is a declaration that silently does nothing, which is exactly the silence this
  repository works to eliminate.
- **`(provider, model)` stopped being an identity.** The same vendor and model id can legitimately
  exist on several connections (two relays fronting the same Gemini), so submission paths that
  carried only the pair either picked an arbitrary connection or listed models the caller cannot
  actually use.
- **Every consumer resolved on its own.** Options listing, submission validation, the settings
  dialog and workflow templates each joined provider models, declarations and catalogues
  themselves, and gave different answers for the same model.

## Decision

1. **Declarations are their own table.** `GenerationCapabilityDeclaration` holds one row per
   `(provider_model_id, kind)`; "follow the catalogue" is expressed by the absence of a row, not by
   an empty value. Image and video are declared independently.

2. **The two sources are separate columns.** `catalog_ref` points into the static catalogue
   (`model:<provider>/<model>` or a named built-in profile); `template_id` points at a
   user-written `GenerationCapabilityProfile` on the same connection. A CHECK constraint enforces
   exactly one source per row, and `template_id` is a real foreign key with `ondelete="RESTRICT"`.

3. **Deleting an in-use template is refused** (HTTP 409 naming the referencing model count) instead
   of leaving dangling refs. The user detaches the models first, so "what was configured" is never
   a question the data cannot answer. This reverses the dangling-ref consequence of ADR 0012.

4. **One module answers "what are this model's parameters".** `app/domain/generation/resolution.py`
   resolves user, connection, model and kind into one effective descriptor — ownership check,
   enabled check, declaration lookup, custom-profile roster, catalogue fallback and known/unknown
   distinction. Options listing, job submission, the settings dialog, workflow templates and the
   agent all call it; the static catalogue stays a leaf and does not reach upward (the import
   layering test pins this).

5. **Submission identity is `(provider_profile_id, model)`.** Boards, the agent, scheduled tasks,
   workflow nodes and the MCP server all carry the connection id alongside the model; legacy calls
   without it must resolve unambiguously or fail loudly rather than pick an arbitrary connection.

6. **The legacy column is read, not written.** Rows predating the split still honour
   `ProviderModel.generation_capability_ref` as a per-kind fallback; a new-path write clears it
   only once it covers every generation kind of the model — a partial write must not strand the
   kinds it did not mention. The column is removed once a migration window has passed and no
   reader remains.

## Consequences

- A dual-capability model is configured per kind; neither half can silently inherit the other.
- The database, not a string convention, keeps declaration references valid.
- Deleting a template has an explicit, communicated behaviour instead of a silent fallback.
- Changing resolution rules touches one module; all callers change together.
- Templates, boards, the agent and scheduled tasks submit against the exact connection the user
  configured, and a genuinely ambiguous legacy submission fails with an explanation instead of
  using somebody else's endpoint.
- Until the legacy column is removed, `declaration_refs_for_model` carries the compatibility shim;
  it is the only place that knows both worlds.
