/** @vitest-environment jsdom */
/**
 * 社区(ADR 0026)在应用里的三处界面:设置里的「社区账号」、画板的「分享」面板、「发布到社区」弹窗。
 *
 * 钉住的是人会碰到的状态:没配社区 / 没连 / 等你在浏览器里点允许(配对码大字显示、自动连上)/ 已连接;
 * 分享面板没连账号时指路、生成链接之后显示链接和版本、改可见性当场存、撤回要确认;发布之后给链接,
 * 插件说「审核中」。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  status: vi.fn(),
  connect: vi.fn(),
  poll: vi.fn(),
  cancelConnect: vi.fn(async () => undefined),
  disconnect: vi.fn(async () => undefined),
  boardShare: vi.fn(),
  shareBoard: vi.fn(),
  updateShare: vi.fn(),
  withdraw: vi.fn(async () => undefined),
  getJob: vi.fn(),
  cancelJob: vi.fn(),
  publishWorkflow: vi.fn(),
  publishPlugin: vi.fn(),
  listAssets: vi.fn(async () => []),
}));

vi.mock("@/api/client", () => ({
  getCommunityStatus: mocks.status,
  startCommunityConnect: mocks.connect,
  pollCommunityConnect: mocks.poll,
  cancelCommunityConnect: mocks.cancelConnect,
  disconnectCommunity: mocks.disconnect,
  communityPage: (origin: string, page: string) => `${origin}/me/${page}`,
  getBoardShare: mocks.boardShare,
  shareBoard: mocks.shareBoard,
  updateBoardShare: mocks.updateShare,
  withdrawBoardShare: mocks.withdraw,
  getJob: mocks.getJob,
  cancelJob: mocks.cancelJob,
  publishWorkflowToCommunity: mocks.publishWorkflow,
  publishPluginToCommunity: mocks.publishPlugin,
  listAssets: mocks.listAssets,
  assetThumbnailUrl: (id: string) => `thumb://${id}`,
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ t: (key: string) => key, locale: "zh-CN" }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

import { BoardShareDialog } from "@/features/community/BoardShareDialog";
import { CommunityAccountSection } from "@/features/community/CommunityAccountSection";
import { PublishPluginDialog } from "@/features/community/PublishPluginDialog";
import { PublishWorkflowDialog } from "@/features/community/PublishWorkflowDialog";

const ORIGIN = "https://community.test";
const DISCONNECTED = { configured: true, origin: ORIGIN, connected: false, handle: "", display_name: "", pending: null };
const CONNECTED = { ...DISCONNECTED, connected: true, handle: "alice", display_name: "Alice" };
const PENDING = { ...DISCONNECTED, pending: { user_code: "ABCD-1234", verification_uri: `${ORIGIN}/zh/device?code=ABCD-1234`, expires_in: 600 } };

function wrap(node: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  mocks.listAssets.mockResolvedValue([]);
  mocks.cancelConnect.mockResolvedValue(undefined);
  mocks.disconnect.mockResolvedValue(undefined);
  mocks.withdraw.mockResolvedValue(undefined);
  vi.spyOn(window, "open").mockImplementation(() => null);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("设置 → 社区账号", () => {
  it("没配社区时说清楚,不给连接键", async () => {
    mocks.status.mockResolvedValue({ ...DISCONNECTED, configured: false, origin: "" });
    wrap(<CommunityAccountSection />);
    expect(await screen.findByText("communityNotConfigured")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /communityConnect/ })).toBeNull();
  });

  it("连接:打开浏览器、显示配对码、等到允许就连上", async () => {
    mocks.status.mockResolvedValueOnce(DISCONNECTED).mockResolvedValue(PENDING);
    mocks.connect.mockResolvedValue(PENDING.pending);
    mocks.poll.mockResolvedValue({ state: "connected", status: CONNECTED });
    wrap(<CommunityAccountSection />);

    fireEvent.click(await screen.findByRole("button", { name: /communityConnect/ }));
    await waitFor(() => expect(window.open).toHaveBeenCalledWith(PENDING.pending.verification_uri, "_blank", "noopener"));
    expect((await screen.findByTestId("community-user-code")).textContent).toBe("ABCD-1234");
    expect(screen.getByRole("button", { name: /communityOpenInBrowser/ })).toBeTruthy();

    // 后端节流;这里每两秒问一次,问到「连上了」就换成已连接的样子。
    expect(await screen.findByText("communityConnectedAs", {}, { timeout: 4000 })).toBeTruthy();
    expect(screen.queryByTestId("community-user-code")).toBeNull();
  });

  it("已连接:给「我的提交」「我的分享」两条网站链接,能断开", async () => {
    mocks.status.mockResolvedValue(CONNECTED);
    wrap(<CommunityAccountSection />);
    const submissions = await screen.findByRole("link", { name: /communityMySubmissions/ });
    expect(submissions.getAttribute("href")).toBe(`${ORIGIN}/me/submissions`);
    expect(screen.getByRole("link", { name: /communityMyShares/ }).getAttribute("href")).toBe(`${ORIGIN}/me/shares`);
    fireEvent.click(screen.getByRole("button", { name: /communityDisconnect/ }));
    await waitFor(() => expect(mocks.disconnect).toHaveBeenCalled());
  });
});

describe("画板 → 分享", () => {
  const SHARE = { slug: "b1", url: `${ORIGIN}/zh/b/b1`, version: 2, title: "灵感", visibility: "unlisted", updated_at: "2026-09-27T10:00:00" };

  function panel() {
    return wrap(<BoardShareDialog open onOpenChange={vi.fn()} boardId="board-1" boardName="灵感" workspaceId="ws" />);
  }

  it("没连社区账号:指去设置,不给生成链接", async () => {
    mocks.boardShare.mockResolvedValue({ share: null, status: DISCONNECTED });
    panel();
    expect(await screen.findByText("boardShareNeedsAccount")).toBeTruthy();
    expect(screen.getByRole("button", { name: /communityGoConnect/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /boardShareCreate/ })).toBeNull();
  });

  it("生成链接:排任务、做完显示链接和版本", async () => {
    mocks.boardShare.mockResolvedValueOnce({ share: null, status: CONNECTED }).mockResolvedValue({ share: SHARE, status: CONNECTED });
    mocks.shareBoard.mockResolvedValue({ id: "job-1", status: "queued" });
    mocks.getJob.mockResolvedValue({ id: "job-1", status: "succeeded", progress: 1, message: "", error: null });
    panel();

    fireEvent.click(await screen.findByRole("button", { name: /boardShareCreate/ }));
    await waitFor(() =>
      expect(mocks.shareBoard).toHaveBeenCalledWith("board-1", { workspace_id: "ws", title: "灵感", visibility: "unlisted" }),
    );
    const link = (await screen.findByRole("textbox", { name: "boardShareLink" })) as HTMLInputElement;
    expect(link.value).toBe(SHARE.url);
    expect(screen.getByRole("button", { name: /boardShareUpdate/ })).toBeTruthy();
  });

  it("已分享:改可见性当场存,撤回要先确认", async () => {
    mocks.boardShare.mockResolvedValue({ share: SHARE, status: CONNECTED });
    mocks.updateShare.mockResolvedValue({ ...SHARE, visibility: "public" });
    panel();

    fireEvent.click(await screen.findByRole("radio", { name: /boardSharePublic/ }));
    await waitFor(() => expect(mocks.updateShare).toHaveBeenCalledWith("board-1", { workspace_id: "ws", visibility: "public" }));

    fireEvent.click(screen.getByRole("button", { name: /boardShareWithdraw/ }));
    expect(mocks.withdraw).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "boardShareWithdraw" }));
    await waitFor(() => expect(mocks.withdraw).toHaveBeenCalledWith("board-1", "ws"));
  });
});

describe("发布到社区", () => {
  const WORKFLOW = {
    id: "wf-1", workspace_id: "ws", name: "批量配音", description: "一次配完", graph: {}, revision: 3, graph_hash: "",
    community_slug: "", created_at: "", updated_at: "",
  };

  it("工作流:填好就发,拿回链接", async () => {
    mocks.publishWorkflow.mockResolvedValue({ slug: "wf1", url: `${ORIGIN}/zh/workflows/wf1`, version: "1", status: "published" });
    wrap(<PublishWorkflowDialog open onOpenChange={vi.fn()} workflow={WORKFLOW} />);
    fireEvent.change(screen.getByRole("textbox", { name: "communityFieldTags" }), { target: { value: "配音, 批量,配音" } });
    fireEvent.click(screen.getByRole("button", { name: /^communityPublish$/ }));
    await waitFor(() =>
      expect(mocks.publishWorkflow).toHaveBeenCalledWith("wf-1", {
        title: "批量配音", summary: "一次配完", tags: ["配音", "批量"], cover_asset_id: null,
      }),
    );
    expect(await screen.findByText("communityStatusPublished")).toBeTruthy();
    expect((screen.getByRole("textbox", { name: "boardShareLink" }) as HTMLInputElement).value).toBe(`${ORIGIN}/zh/workflows/wf1`);
  });

  it("工作流:发过的再发,说的是「发布新版本」", () => {
    wrap(<PublishWorkflowDialog open onOpenChange={vi.fn()} workflow={{ ...WORKFLOW, community_slug: "wf1" }} />);
    expect(screen.getByText("communityPublishWorkflowAgain")).toBeTruthy();
    expect(screen.getByRole("button", { name: /communityPublishNewVersion/ })).toBeTruthy();
  });

  it("插件:发完显示审核中", async () => {
    mocks.publishPlugin.mockResolvedValue({ slug: "demo", url: `${ORIGIN}/zh/plugins/demo`, version: "1.0.0", status: "pending" });
    wrap(<PublishPluginDialog open onOpenChange={vi.fn()} plugin={{ id: "dev.test.demo", name: "演示", version: "1.0.0" }} />);
    fireEvent.click(screen.getByRole("button", { name: /^communityPublish$/ }));
    await waitFor(() => expect(mocks.publishPlugin).toHaveBeenCalledWith("dev.test.demo", { summary: "", tags: [] }));
    expect(await screen.findByText("communityStatusPending")).toBeTruthy();
    expect(screen.getByText("communityPendingBody")).toBeTruthy();
  });
});
