export type VideoPlatform = "youtube" | "bilibili" | "pornhub" | "generic";

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
  /** yt-dlp extractor selected by the backend for players without a readable HTML video. */
  extractor?: string;
  /** Whether the page exposes a video element that can seek and return decoded pixels. */
  playable: boolean;
  title: string;
  url: string;
  currentTime: number;
  duration: number;
};
