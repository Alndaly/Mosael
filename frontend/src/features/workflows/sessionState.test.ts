import { describe, expect, it } from "vitest";

import {
  mergeWorkflowAgentSessions,
  nextWorkflowAgentSessionAfterDelete,
  resolveWorkflowAgentSession,
} from "@/features/workflows/sessionState";

const session = (id: string) => ({ id });

describe("workflow agent session state", () => {
  it("uses the selected session when it is present", () => {
    expect(resolveWorkflowAgentSession("manual", session("default"), [session("manual"), session("default")])?.id).toBe("manual");
  });

  it("falls back to the default session when localStorage points at a deleted session", () => {
    expect(resolveWorkflowAgentSession("deleted", session("default"), [session("manual"), session("default")])?.id).toBe("default");
  });

  it("keeps the default session selectable while the list query is still empty", () => {
    expect(mergeWorkflowAgentSessions(session("default"), []).map((item) => item.id)).toEqual(["default"]);
  });

  it("chooses another session after deleting the active one", () => {
    expect(nextWorkflowAgentSessionAfterDelete("manual-a", session("default"), [session("manual-a"), session("manual-b")])?.id).toBe("default");
  });

  it("returns null after deleting the only known session", () => {
    expect(nextWorkflowAgentSessionAfterDelete("default", session("default"), [])).toBeNull();
  });
});
