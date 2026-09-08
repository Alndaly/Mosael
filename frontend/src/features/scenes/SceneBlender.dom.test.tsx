/** @vitest-environment jsdom */
/**
 * 「还用不了」的四个状态各自要答出**接下来做什么**。
 *
 * 这条测试是补写的:此前四个状态里只有「缺插件」给了出路,另外三个是裸的一行灰字。
 * 而读者从「长得不一样」读出的是"这里坏了",不是"这里还没有东西"——
 * 见 components/layout/EmptyState 的说明。
 *
 * 钉的不是文案(那会随产品判断改),是**每个状态都有标题、有说明、有下一步**。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.fn();
vi.mock("@/api/transport", () => ({
  api: (...args: unknown[]) => api(...args),
  API_BASE: "",
  getAuthToken: () => "t",
}));

import { SceneBlender } from "./SceneBlender";

const scene = { id: "s1", workspace_id: "w1", name: "展厅", revision: 3,
  content: { shots: [{ id: "shot-1" }] } } as never;

/** 面板同时拉两份数据:连接列表和传输历史。**按 URL 分派** —— 让两个查询拿同一个对象,
 *  历史那边会收到一个没有 filter 的东西,报出来的错和真正要测的东西毫无关系。 */
function serve(connections: unknown, { fail = false } = {}) {
  api.mockImplementation((path: string) => {
    if (String(path).includes("/blender/connections")) {
      return fail ? Promise.reject(new Error("后端没起来")) : Promise.resolve(connections);
    }
    return Promise.resolve([]);   // 传输历史
  });
}

function open(apply = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SceneBlender
        scene={scene}
        pending={false}
        busy={false}
        prepare={vi.fn(async () => ({ revision: 3, shotId: "shot-1", blob: new Blob() }))}
        apply={apply}
        work={vi.fn(async (_label: string, fn: () => Promise<void>) => { await fn(); })}
      />
    </QueryClientProvider>,
  );
  screen.getByRole("button", { name: /Blender/ }).click();
  return apply;
}

afterEach(cleanup);
beforeEach(() => api.mockReset());

describe("用不了的时候", () => {
  it("后端不在本机:说清为什么,并给下载桌面版的出路", async () => {
    // 团队服务器部署上这是**永久**状态 —— 互通要把 .blend 写到本机磁盘再交给同机的
    // Blender,服务器上的后端够不到你的电脑。所以出路不是"去设置",是换个客户端。
    serve({ local: false, connections: [] });
    open();
    await screen.findByText("需要桌面版 Mosael");
    expect(screen.getByText(/够不到它/)).toBeTruthy();
    expect(screen.getByRole("link", { name: /下载桌面版/ })).toBeTruthy();
  });

  it("本机但没接插件:给「前往插件设置」和「查看安装步骤」两条路", async () => {
    serve({ local: true, connections: [] });
    open();
    await screen.findByText("还没接上 Blender");
    expect(screen.getByRole("link", { name: /前往插件设置/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /查看安装步骤/ })).toBeTruthy();
  });

  it("读不到连接列表:把真正的错误说出来,并给重试按钮", async () => {
    // 不是「请刷新重试」这种万金油 —— 错误本身是用户唯一能拿去搜的线索。
    serve(null, { fail: true });
    open();
    await screen.findByText("读不到连接列表");
    await waitFor(() => expect(screen.getByText(/后端没起来/)).toBeTruthy());
    expect(screen.getByRole("button", { name: /重试/ })).toBeTruthy();
  });
});

describe("接收", () => {
  const ready = {
    id: "t1", instance_id: "i1", status: "ready", source_revision: 3,
    scene_name: "Mosael · 展厅", created_at: "2026-09-08T00:00:00Z",
    received_scene_id: null, warnings: null, error: null,
  };
  const content = { shots: [{ id: "shot-1" }], objects: [{ id: "blender-model" }] };

  function serveReady() {
    api.mockImplementation((path: string, init?: { method?: string }) => {
      const url = String(path);
      if (url.includes("/blender/connections"))
        return Promise.resolve({ local: true, connections: [{ id: "i1", name: "Blender MCP", enabled: true }] });
      if (init?.method === "POST" && url.includes("/receive"))
        return Promise.resolve({ ...ready, content });
      return Promise.resolve([ready]);
    });
  }

  it("默认落在当前场景上,而不是另建一个", async () => {
    // 这条钉的是**去处**,不是文案:接收要走 into_current,并把内容交回编辑器 ——
    // 由它当成一次可撤销的改动写下去。绕过编辑器直接写库的话,编辑器手上那份草稿立刻就旧了。
    serveReady();
    const apply = open();
    (await screen.findByText("接收 Blender 修改")).click();
    await waitFor(() => expect(apply).toHaveBeenCalledWith(content));
    const call = api.mock.calls.find((args) => String(args[0]).includes("/receive"));
    expect(String(call?.[0])).toContain("into_current=true");
  });

  it("要留原样的,另存为新场景还在", async () => {
    serveReady();
    const apply = open();
    (await screen.findByRole("button", { name: "另存为新场景" })).click();
    await waitFor(() => {
      const call = api.mock.calls.find((args) => String(args[0]).includes("/receive"));
      expect(call && !String(call[0]).includes("into_current")).toBe(true);
    });
    expect(apply).not.toHaveBeenCalled();
  });
});
