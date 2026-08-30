import { describe, expect, it } from "vitest";

import * as client from "@/api/client";
import * as browser from "@/api/domains/browser";
import * as publish from "@/api/domains/publish";
import * as transport from "@/api/transport";

describe("unified API client assembly", () => {
  it("re-exports the transport seam", () => {
    expect(client.api).toBe(transport.api);
    expect(client.setAuthToken).toBe(transport.setAuthToken);
  });

  it("re-exports the publishing domain client", () => {
    expect(client.listPublishAccounts).toBe(publish.listPublishAccounts);
    expect(client.createPublishTask).toBe(publish.createPublishTask);
  });

  it("re-exports the browser domain client", () => {
    expect(client.listBrowserProfiles).toBe(browser.listBrowserProfiles);
    expect(client.createBrowserProfile).toBe(browser.createBrowserProfile);
  });
});
