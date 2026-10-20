// The "default" layer of transcription models — Admin → Engines → Transcription models.
// The five cards' own names/descriptions live in aiStudio.ts (asrModels*); this area holds the default action.
export const transcription = {
  asrDefaultHint:
    "A model that's already on disk can be set as this machine's default — pick it in the row below; transcription uses it by default. “Speech input engine” under voice conversation overrides it per purpose; blank falls back here.",
  asrModelIsDefault: "Default model",
  //: With no default saved, the selector says what happens instead: an automatic pick
  //: (see domain/asr.resolve_asr_model).
  asrDefaultAuto: "Automatic (none set)",
} as const;
