/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { messages } from "@/app/messages";
import { createMutationCache } from "@/app/mutationErrors";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AppShell } from "./AppShell";
import type { Workspace } from "@/api/client";

const zh = messages["zh-CN"];
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: keyof typeof zh) => zh[key],
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("@/app/auth", () => ({ useAuth: () => ({ user: { id: "u1", username: "kinda" }, logout: vi.fn() }) }));

const created: Workspace = { id: "ws-new", name: "新工作区", role: "owner" } as Workspace;
/** 服务端的列表:建完之后**真的**会带上新工作区(用户说刷新之后看得见,所以服务端是对的)。 */
let server: Workspace[] = [{ id: "ws-1", name: "默认工作区", role: "owner" } as Workspace];
const listed = vi.fn(async () => server);
const createWorkspace = vi.fn(async (name: string) => { server = [created, ...server]; return { ...created, name }; });
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  createWorkspace: (name: string) => createWorkspace(name),
  renameWorkspace: vi.fn(),
  deleteWorkspace: vi.fn(),
}));

/** 复刻 App.tsx 里 WorkspaceGate 的接线:列表来自 useQuery,当前工作区由 activeId 解析。 */
function Gate({ onResolve }: { onResolve: (id: string) => void }) {
  const workspaces = useQuery({ queryKey: ["workspaces"], queryFn: () => listed() });
  const [activeId, setActiveId] = React.useState<string | null>("ws-1");
  const list = workspaces.data;
  const workspace = list?.find((one) => one.id === activeId) ?? list?.[0] ?? null;
  React.useEffect(() => { if (workspace) onResolve(workspace.id); }, [workspace, onResolve]);
  if (!workspace) return null;
  return (
    <TooltipProvider>
      <AppShell
        view="home" onViewChange={vi.fn()}
        workspaceId={workspace.id} workspaceName={workspace.name}
        workspaces={list ?? []} onSelectWorkspace={setActiveId}
        projectName={null} projects={[]} currentProjectId={null} onSwitchProject={vi.fn()}
      >
        <div />
      </AppShell>
    </TooltipProvider>
  );
}

function shell() {
  const client = new QueryClient({
    mutationCache: createMutationCache(() => undefined),
    defaultOptions: { queries: { staleTime: 60_000, refetchOnWindowFocus: false, retry: 1 } },
  });
  const resolved: string[] = [];
  const view = render(
    <QueryClientProvider client={client}>
      <Gate onResolve={(id) => resolved.push(id)} />
    </QueryClientProvider>,
  );
  return { ...view, client, resolved };
}

/**
 * 新建工作区之后,列表里要立刻有它,而且要切过去。
 *
 * 这两件事此前都要刷新一次才发生 —— 而"刷新一下就好了"是最容易被当成偶发、其实每次都复现
 * 的一类问题:新建完什么也没发生,用户只会以为自己没点到。
 */
it("新建之后立刻出现在列表里,并且切了过去", async () => {
  const { client, resolved } = shell();
  await screen.findByRole("button", { name: new RegExp(zh.workspaceSwitch) });
  fireEvent.click(screen.getByRole("button", { name: new RegExp(zh.workspaceSwitch) }));
  fireEvent.click(await screen.findByRole("button", { name: zh.workspaceNew }));
  const box = await screen.findByRole("textbox");
  fireEvent.change(box, { target: { value: "新工作区" } });
  // jsdom 不会因为点提交按钮而提交表单,直接发 submit —— 测的是提交之后发生什么。
  fireEvent.submit(box.closest("form")!);

  await waitFor(() => expect(createWorkspace).toHaveBeenCalledWith("新工作区"));
  await waitFor(() =>
    expect(client.getQueryData<Workspace[]>(["workspaces"])?.map((one) => one.id)).toContain("ws-new"),
  );
  // 解析出来的当前工作区必须变成新建的那个,而不是弹回原来的。
  await waitFor(() => expect(resolved[resolved.length - 1]).toBe("ws-new"));
});

