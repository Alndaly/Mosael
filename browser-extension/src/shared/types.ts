export type VideoPlatform = "youtube" | "bilibili" | "pornhub";

export type TranscriptToken = {
  start: number;
  end: number;
  text: string;
};

export type TranscriptCue = {
  start: number;
  end: number;
  text: string;
  /** Exact ASR alignment, when the provider returned it. Kept so transcript words stay seekable. */
  tokens?: TranscriptToken[];
};

export type TranscriptTrack = {
  id: string;
  language: string;
  languageLabel: string;
  kind: "source" | "translated";
};

export type Transcript = {
  trackId: string;
  language: string;
  languageLabel: string;
  cues: TranscriptCue[];
  tracks: TranscriptTrack[];
};

export type VideoContext = {
  supported: boolean;
  platform?: VideoPlatform;
  title: string;
  url: string;
  currentTime: number;
  duration: number;
};
