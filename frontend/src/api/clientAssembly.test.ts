import { describe, expect, it } from "vitest";

import * as client from "@/api/client";
import * as browser from "@/api/domains/browser";
import * as jobs from "@/api/domains/jobs";
import * as notifications from "@/api/domains/notifications";
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

  it("re-exports the task-bus domain client", () => {
    expect(client.getJob).toBe(jobs.getJob);
    expect(client.listJobEvents).toBe(jobs.listJobEvents);
  });

  it("re-exports the notification domain client", () => {
    expect(client.listNotifications).toBe(notifications.listNotifications);
    expect(client.readNotification).toBe(notifications.readNotification);
  });
});
