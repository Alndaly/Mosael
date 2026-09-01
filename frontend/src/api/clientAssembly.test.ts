import { describe, expect, it } from "vitest";

import * as client from "@/api/client";
import * as boards from "@/api/domains/boards";
import * as browser from "@/api/domains/browser";
import * as jobs from "@/api/domains/jobs";
import * as notifications from "@/api/domains/notifications";
import * as publish from "@/api/domains/publish";
import * as scheduler from "@/api/domains/scheduler";
import * as workflows from "@/api/domains/workflows";
import * as transport from "@/api/transport";

describe("unified API client assembly", () => {
  it("re-exports the transport seam", () => {
    expect(client.api).toBe(transport.api);
    expect(client.setAuthToken).toBe(transport.setAuthToken);
  });

  it("re-exports the infinite-canvas domain client", () => {
    expect(client.listBoards).toBe(boards.listBoards);
    expect(client.generateOnBoard).toBe(boards.generateOnBoard);
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

  it("re-exports the scheduler domain client", () => {
    expect(client.listScheduledTasks).toBe(scheduler.listScheduledTasks);
    expect(client.runScheduledTask).toBe(scheduler.runScheduledTask);
  });

  it("re-exports the workflow domain client", () => {
    expect(client.listWorkflows).toBe(workflows.listWorkflows);
    expect(client.runWorkflow).toBe(workflows.runWorkflow);
  });
});
