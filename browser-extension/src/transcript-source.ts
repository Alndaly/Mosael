import type { GeneratedTranscript } from "./mosael/client";
import type { Transcript } from "./shared/types";

type ResolvedTranscript = {
  origin: "site" | "mosael";
  transcript: Transcript;
};

export async function resolveTranscriptSource(
  readSite: () => Promise<Transcript>,
  readStored?: () => Promise<GeneratedTranscript | null>,
): Promise<ResolvedTranscript> {
  try {
    return { origin: "site", transcript: await readSite() };
  } catch (siteError) {
    const stored = readStored ? await readStored() : null;
    if (!stored) throw siteError;
    return {
      origin: "mosael",
      transcript: {
        trackId: `mosael:${stored.assetId}`,
        language: stored.language,
        languageLabel: stored.language ? `Mosael · ${stored.language}` : "Mosael",
        cues: stored.cues,
        tracks: [],
      },
    };
  }
}
