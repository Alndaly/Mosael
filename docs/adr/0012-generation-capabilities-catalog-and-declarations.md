# ADR 0012: Generation capabilities are a catalog plus a per-model declaration

## Status

Accepted — 2026-09-15. Storage half superseded by [ADR 0013](0013-generation-declarations-per-model-kind.md):
the single `generation_capability_ref` column became per-`(model, kind)` declaration rows, and
deleting an in-use custom profile is now refused instead of left dangling. The catalogue, the named
capability profiles and the "shape, not fact" validation of this ADR still stand.

## Context

Generation parameters (sizes, durations, reference-image roles and limits) come from a static table
keyed by `(provider, model, kind)`. A miss falls back to a descriptor that declares nothing, so the
UI offers a prompt box and no parameters at all.

On a real installation, 10 of 24 configured models missed the table. Six of those sat on one relay
connection: four Gemini image models, a hand-added `gpt-image-2-client` alias, and a local `gemma4`.
The models plainly do accept parameters; the catalog simply did not know them under that provider.

The obvious repair — when the vendor is a relay, retry the lookup by model id across vendors — is
wrong, and measurement showed why. The catalog holds one model under two providers, and the two rows
genuinely differ: `qwen-image-edit` on Alibaba's own endpoint accepts only `reference_image`, three
of them, image-to-image only; through the Evolink relay it also accepts `size` and `num_images`, and
fourteen references. Cross-vendor inheritance would have offered Alibaba's endpoint parameters it
rejects. **The provider is not a transport label; it materially changes what the endpoint accepts.**

The structural problem lay elsewhere. Of 58 catalog rows, 9 capability objects were shared by 28
rows, and one pair was a literal duplicate (`gpt-image-2` under both `openai` and
`openai-compatible`). The table is a mapping from `(provider, model)` onto a small vocabulary of
capability shapes — but the shapes had no names, so every "this model is also reachable another way"
could only be answered by copying a row.

The second half of the problem was that the user had nowhere to record what only they know.
`ProviderModel` already carries a block of per-row overrides — `context_window`, `reasoning`,
`vision`, `reasoning_effort`, `developer_role` — and every one of them serves chat. Generation had
none. A user who knows their `-client` row is the same model, or who knows their relay's Gemini
takes a size, could only wait for us to add a catalog row.

## Decision

1. **Capability profiles are named.** Every capability constant has a stable id
   (`openai-image`, `evolink-image-edit`, …) in `CAPABILITY_PROFILES`. A test requires that every
   capabilities object reachable from `BUILTIN_MODELS` has one, so a new shape cannot be added
   without a name — an anonymous object cannot be pointed at.

2. **A model row may declare where its generation parameters come from.**
   `ProviderModel.generation_capability_ref` is nullable and follows the same convention as the
   fields beside it: empty means follow the catalog. Two spellings, one concept:
   - `model:<provider>/<model>` — "it behaves like X". A pointer, not a snapshot: widening X's
     descriptor later widens every row pointing at it.
   - `profile:<id>` — a capability profile directly, for combinations the catalog has no model for.

3. **Resolution order is declaration → exact catalog match → fallback. Nothing is inferred.** Either
   the catalog knows the model, or the user said so. A pointer does not cross `kind`; a pointer to
   something deleted resolves to `None` rather than raising.

4. **Two zeros are distinguished.** `capabilities_known` separates "this model genuinely has no
   adjustable parameters" from "we do not recognise this model". Collapsing them makes the second
   look like the first, and the UI then silently offers nothing.

5. **Users may define their own profiles, owned by the connection.**
   `GenerationCapabilityProfile` hangs off `ProviderProfile` with `ondelete="CASCADE"`: a profile
   describes what the endpoint behind that connection accepts, so the two live and die together and
   no orphan can point at a deleted connection. Connections are already per-person, so ownership
   needs no second mechanism.

6. **Saving validates shape, not fact.** Unknown keys are rejected by name, lists must be lists,
   limits must be positive integers, and a default must appear in its own list. What cannot be
   validated — whether the endpoint really accepts four images — is stated in the UI: a custom
   profile is the user's assertion, and a wrong value fails when the provider rejects the request.

## Consequences

- A relay-configured model gets its parameters by one declaration instead of a code change.
- The catalog stays a record of what we verified. User assertions are visibly separate from it.
- A model we do not recognise now says so instead of appearing to have no parameters.
- Deleting a custom profile leaves the pointing rows' `ref` in place; they fall back to "not
  recognised" rather than silently reverting to "follow the catalog", so the user can still see
  what they had configured.
- Adding a new capability shape now requires naming it. That is the intended cost.
