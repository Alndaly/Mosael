import type { Transcript, VideoContext } from "./types";
import type { PlatformResourceResponse } from "../platform-resource";

export const PAGE_REQUEST_CHANNEL = "openstudio-extension";
export const PAGE_RESPONSE_CHANNEL = "openstudio-extension-page";
export const PAGE_RESOURCE_REQUEST_CHANNEL = "openstudio-extension-resource";
export const PAGE_RESOURCE_RESPONSE_CHANNEL = "openstudio-extension-resource-response";

export type PlatformResourceRequest = { type: "FETCH_PLATFORM_RESOURCE"; url: string };

export type ContentRequest =
  | { type: "GET_CONTEXT" }
  | { type: "GET_TRANSCRIPT"; trackId?: string }
  | { type: "SEEK"; seconds: number }
  | { type: "CAPTURE_VIDEO_FRAME" }
  | { type: "PREPARE_FRAME_CAPTURE" }
  | { type: "RESTORE_FRAME_CAPTURE" };

export type CapturedVideoFrame = {
  dataUrl: string;
  currentTime: number;
  title: string;
};

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
  | { ok: true; data: VideoContext | Transcript | CapturedVideoFrame | CaptureGeometry | { currentTime: number } }
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

export type PageResourceRequest = {
  channel: typeof PAGE_RESOURCE_REQUEST_CHANNEL;
  id: string;
  type: "FETCH_PLATFORM_RESOURCE";
  url: string;
};

export type PageResourceResponse = PlatformResourceResponse & {
  channel: typeof PAGE_RESOURCE_RESPONSE_CHANNEL;
  id: string;
};
