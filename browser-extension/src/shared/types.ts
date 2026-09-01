export type VideoPlatform = "youtube" | "bilibili";

export type TranscriptCue = {
  start: number;
  end: number;
  text: string;
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
