export type VideoPlatform = "youtube" | "bilibili";

export type TranscriptCue = {
  start: number;
  end: number;
  text: string;
};

export type Transcript = {
  language: string;
  languageLabel: string;
  cues: TranscriptCue[];
};

export type VideoContext = {
  supported: boolean;
  platform?: VideoPlatform;
  title: string;
  url: string;
  currentTime: number;
  duration: number;
};
