import type { GeneratedTranscript } from "./openstudio/client";
import type { Transcript } from "./shared/types";

type ResolvedTranscript = {
  origin: "site" | "openstudio";
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
      origin: "openstudio",
      transcript: {
        trackId: `openstudio:${stored.assetId}`,
        language: stored.language,
        languageLabel: stored.language ? `Open Studio · ${stored.language}` : "Open Studio",
        cues: stored.cues,
        tracks: [],
      },
    };
  }
}
