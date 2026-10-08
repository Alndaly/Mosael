/** @vitest-environment jsdom */
import { afterEach, expect, it } from "vitest";

import { aiStudioHref, gotoAiChat, gotoCreate, openCreationSession, parseAiStudioHash } from "@/lib/aiStudioLink";
import { hasPendingOpenRequest } from "@/lib/deepLink";

afterEach(() => {
  window.location.hash = "";
});

it("深链来回:分区、会话、筛选;认不出的值不当真", () => {
  expect(aiStudioHref("create", { session: "s1", kind: "speech" })).toBe("#/ai?tab=create&session=s1&kind=speech");
  expect(parseAiStudioHash("#/ai?tab=create&session=s1&kind=speech")).toEqual({ tab: "create", session: "s1", kind: "speech" });
  expect(parseAiStudioHash("#/ai?tab=generate&kind=music")).toEqual({ tab: null, session: "", kind: null });
  expect(parseAiStudioHash("#/ai")).toEqual({ tab: null, session: "", kind: null });
  expect(parseAiStudioHash("#/boards?board=b1")).toBeNull();
});

it("去对话写明 tab=chat;打开一条创作会话走信箱;去创作带筛选", () => {
  gotoAiChat();
  expect(window.location.hash).toBe("#/ai?tab=chat");
  openCreationSession("s9");
  expect(window.location.hash).toBe("#/ai?tab=create");
  expect(hasPendingOpenRequest("mosael:open-creation-session")).toBe(true);
  gotoCreate("audio");
  expect(hasPendingOpenRequest("mosael:creation-filter")).toBe(true);
});
