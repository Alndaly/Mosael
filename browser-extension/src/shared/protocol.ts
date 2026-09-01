import type { Transcript, VideoContext } from "./types";

export const PAGE_REQUEST_CHANNEL = "openstudio-extension";
export const PAGE_RESPONSE_CHANNEL = "openstudio-extension-page";

export type ContentRequest =
  | { type: "GET_CONTEXT" }
  | { type: "GET_TRANSCRIPT"; trackId?: string }
  | { type: "SEEK"; seconds: number }
  | { type: "GET_CAPTURE_GEOMETRY" };

export type CaptureGeometry = {
  left: number;
  top: number;
  width: number;
  height: number;
  viewportWidth: number;
  viewportHeight: number;
  currentTime: number;
  title: string;
};

export type ContentResponse =
  | { ok: true; data: VideoContext | Transcript | CaptureGeometry | { currentTime: number } }
  | { ok: false; error: string };

export type PageRequest = {
  channel: typeof PAGE_REQUEST_CHANNEL;
  id: string;
  type: "READ_TRANSCRIPT";
  trackId?: string;
};

export type PageResponse = {
  channel: typeof PAGE_RESPONSE_CHANNEL;
  id: string;
  ok: boolean;
  data?: Transcript;
  error?: string;
};
