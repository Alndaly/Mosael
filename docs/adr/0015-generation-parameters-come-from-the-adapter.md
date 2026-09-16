# ADR 0015: The parameter vocabulary belongs to the adapter, not to the user

## Status

Proposed — 2026-09-16. No code written. Amends the fallback of ADR 0012 (decision 3) and demotes
its user-authored profiles (decisions 5 and 6) from the primary path to an expert escape hatch.
ADR 0013's per-`(model, kind)` declarations and single resolution seam stand unchanged.

## Context

ADR 0012 established that a missing catalogue entry falls back to a descriptor that declares
nothing, and that a user may supply what the catalogue lacks. ADR 0013 fixed how that declaration
is stored. Shipping both produced a settings surface that seven follow-up commits could not settle,
and the owner reported the configuration logic and interaction as seriously wrong.

The measurements behind that report:

- The same concept lives in three places: the legacy `ProviderModel.generation_capability_ref`
  column (still read, retired by a "only safe once every kind is covered" condition), the
  `GenerationCapabilityDeclaration` rows with two mutually exclusive columns, and the
  `GenerationCapabilityProfile` templates.
- `profile:<id>` addresses two namespaces at once. Writing a declaration looks the id up in the
  custom-profile table first and falls back to treating it as a built-in profile id, so which kind
  of thing a ref denotes is answered by a database lookup rather than by the ref itself.
- The custom-profile form offers 34 fields, including `exclusive_source_groups`,
  `requires_companion` and `conditional_max_duration_seconds`. The 39 built-in profiles use between
  6 and 18 fields each (median 15), and 11 of the 34 appear in one or two profiles only.

The 34-field form asks a person to restate a vendor's API documentation from memory. When they get
it wrong nothing says so: the request is rejected by the provider at generation time.

### A hypothesis the data refuted

The obvious repair was that the parameter vocabulary is a property of the adapter rather than of
the model, so an unknown model could simply inherit its adapter's vocabulary. Grouping every
catalogue row by `(provider, kind)` — which is exactly the adapter registry key — refutes that as a
general rule:

```
(alibaba, video)      8 models → 5 distinct parameter_keys sets, 1 key in common
(evolink, video)     22 models → 7 distinct sets, 3 keys in common
(bytedance, video)    6 models → 3 distinct sets, 4 keys in common
```

The keys that vary are mostly source roles — `first_frame`, `reference_image`, `reference_video`,
`source_video`. That variation is real: `seedance-2.0-text-to-video` and
`seedance-2.0-image-to-video` are different tasks, and offering a first-frame slot to a
text-to-video model would be a new way to be wrong.

### What that measurement cannot establish, and what can

Six `(provider, kind)` pairs show no variation — `(openai-compatible, image)`, `(openai, image)`,
both ComfyUI pairs, `(google, video)` and `(minimax, video)`. That is not evidence of anything:
each of those pairs has exactly one catalogue row, and one row cannot disagree with itself.

The evidence is the adapter source. `OpenAIImageAdapter` reads `request.model` at two places, both
of which put it into the payload; it never branches on it. Every model routed through it receives
the same request shape, so its parameter surface — `num_images`, `size`, `reference_image`,
`quality`, `background`, `output_format`, `moderation` — is a constant we can state for any model
name, including names we have never seen.

That the claim rests on reading code rather than on grouping data is the reason decision 1 below
makes each adapter state it and a test hold it: a property established by reading is a property
that decays silently.

This is the adapter behind every model the owner reported: four Gemini image models, a
hand-added `gpt-image-2-client` alias, and a local `gemma4`, all on one OpenAI-compatible relay.
Each of them is shown zero parameters today, and the code that would serve them already knows
exactly which seven it is prepared to send.

## Decision

1. **An adapter declares its own parameter surface, and states whether that surface depends on the
   model id.** This is not inference about a vendor's API: it is a description of the request our
   own code constructs. A ratchet test asserts, per adapter, that a surface declared
   model-independent really is — a new `if model ==` branch inside such an adapter fails the build.

2. **The fallback for an unrecognised model on a model-independent adapter is that adapter's
   surface, with no value constraints asserted.** Parameter *keys* come from the adapter; *valid
   values* (sizes, durations, limits) remain unknown until the catalogue or the user supplies them.
   Offering a size field without claiming which sizes are valid is honest; offering nothing is not,
   because it reads as "this model has no parameters".

3. **Adapters whose payload depends on the model keep the conservative fallback**, and what the
   user is asked for there is the task shape — text-to-video, image-to-video, reference-to-video —
   not a parameter specification. One question with a handful of answers, drawn from the source
   roles that adapter implements.

4. **User-authored profiles stop being the primary path.** They remain for combinations no built-in
   profile matches, reached from the model row rather than from a standing settings section. Most
   installations should never see the form.

5. **`capabilities_known` keeps its meaning and gains precision.** It answers "did anyone verify
   the values", which stays false for a fallback surface. The surface itself is separately known,
   so the UI can offer the fields while saying the limits are unverified — instead of today's
   single bit that collapses "no parameters" and "no knowledge".

## Consequences

- The six models on the owner's relay gain their parameters with no configuration at all.
- The number of models that require any user action drops to those on model-dependent adapters,
  and the question put to those users becomes a choice among task shapes.
- The adapter becomes the single source of truth for what can be sent, which is where the code that
  sends it already lives. The catalogue keeps its present job: which values are valid.
- A declared surface can drift from the code that sends it. The ratchet covers the
  model-independence claim; keeping the key list itself honest needs either derivation from the
  adapter or a test per adapter, and that cost is accepted deliberately.
- The three storage locations of ADR 0012 and 0013 are untouched here. Retiring the legacy column
  and separating the two `profile:` namespaces remain open, and are worth doing whether or not this
  ADR is accepted.
