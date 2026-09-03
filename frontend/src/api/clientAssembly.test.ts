import { describe, expect, it } from "vitest";

import * as client from "@/api/client";
import * as assets from "@/api/domains/assets";
import * as boards from "@/api/domains/boards";
import * as browser from "@/api/domains/browser";
import * as editor from "@/api/domains/editor";
import * as generation from "@/api/domains/generation";
import * as identity from "@/api/domains/identity";
import * as jobs from "@/api/domains/jobs";
import * as notifications from "@/api/domains/notifications";
import * as publish from "@/api/domains/publish";
import * as scheduler from "@/api/domains/scheduler";
import * as sessions from "@/api/domains/sessions";
import * as speech from "@/api/domains/speech";
import * as workflows from "@/api/domains/workflows";
import * as workspaces from "@/api/domains/workspaces";
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

  it("re-exports the identity and workspace domain clients", () => {
    expect(client.updateMe).toBe(identity.updateMe);
    expect(client.createWorkspace).toBe(workspaces.createWorkspace);
    expect(client.listMembers).toBe(workspaces.listMembers);
  });

  it("re-exports the asset and editor domain clients", () => {
    expect(client.importAsset).toBe(assets.importAsset);
    expect(client.assetFileUrl).toBe(assets.assetFileUrl);
    expect(client.insertClip).toBe(editor.insertClip);
    expect(client.translateTexts).toBe(editor.translateTexts);
  });

  it("re-exports the speech and generation domain clients", () => {
    expect(client.synthesizeWithEngine).toBe(speech.synthesizeWithEngine);
    expect(client.listProviderModels).toBe(generation.listProviderModels);
    expect(client.optimizeImagePrompt).toBe(generation.optimizeImagePrompt);
  });

  it("re-exports the shared-session domain client", () => {
    expect(client.listSessionGroups).toBe(sessions.listSessionGroups);
    expect(client.setResourceShared).toBe(sessions.setResourceShared);
  });
});
