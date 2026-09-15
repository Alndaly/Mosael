/** @vitest-environment jsdom */
/**
 * 自定义参数组的管理对话框:创建与删除路径。
 *
 * 后端那条链(test_generation_declaration_paths.py)钉住了"声明 → 绑定 → 提交同一份规则";
 * 这里钉它的入口:用户得真的能在这条连接下建出一份、在建错了的时候看到点名字段的报错,
 * 删掉正在使用的模板时看到 409 那句"还有几个模型在用"。入口坏了的话,后端再对也到不了用户手上。
 *
 * 对话框形态:入口在连接行的溢出菜单里(见 ProviderProfilesSection),不再折叠在列表底部。
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (k: string) => k }));

const apiMock = vi.fn();
vi.mock("@/api/client", () => ({ api: (...args: unknown[]) => apiMock(...args) }));

vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

/* 与 ModelSettingsDialog.dom.test.tsx 同一个理由:**引用必须稳定**,否则落草稿的 effect 无限重渲染。 */
const state = { rows: [] as unknown[] };
const LIST = { data: [] as unknown[] };

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => LIST,
  useMutation: ({ mutationFn, onSuccess, onError }: {
    mutationFn: (body: unknown) => Promise<unknown>;
    onSuccess?: () => void;
    onError?: (error: Error) => void;
  }) => ({
    isPending: false,
    mutate: (body: unknown) => mutationFn(body).then(() => onSuccess?.()).catch((error) => onError?.(error)),
  }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));

import { GenerationProfilesDialog } from "./GenerationProfilesSection";

function render_dialog() {
  LIST.data = state.rows;
  return render(<GenerationProfilesDialog profileId="p1" kind="image" open onOpenChange={() => {}} />);
}

it("新建一份参数组:名字和 JSON 正文原样 POST 到这条连接下", async () => {
  state.rows = [];
  apiMock.mockResolvedValue({ id: "x", name: "中转那份", kind: "image", capabilities: {}, ref: "profile:x" });
  render_dialog();

  fireEvent.click(screen.getByText("generationProfilesAdd"));

  fireEvent.change(screen.getByLabelText(/generationProfilesName/), { target: { value: "中转那份" } });
  fireEvent.click(screen.getByText("save"));

  await waitFor(() => expect(apiMock).toHaveBeenCalled());
  const [url, init] = apiMock.mock.calls[0] as [string, { method: string; body: string }];
  expect(url).toBe("/api/settings/providers/p1/generation-profiles");
  expect(init.method).toBe("POST");
  const body = JSON.parse(init.body);
  expect(body.name).toBe("中转那份");
  expect(body.kind).toBe("image");
  expect(body.capabilities.parameter_keys).toEqual(["size"]);
});

it("JSON 坏了不发请求 —— 那句报错该当场出,而不是绕一圈从服务端回来", async () => {
  state.rows = [];
  render_dialog();

  fireEvent.click(screen.getByText("generationProfilesAdd"));
  fireEvent.change(document.querySelector("textarea")!, { target: { value: "{ 这不是 JSON" } });
  fireEvent.click(screen.getByText("save"));

  expect(await screen.findByText("generationProfilesBadJson")).toBeInTheDocument();
  expect(apiMock).not.toHaveBeenCalled();
});

it("删除被占用的参数组时,后端那句 409 原样弹出来", async () => {
  const { toast } = await import("sonner");
  state.rows = [{ id: "x", name: "中转那份", kind: "image", capabilities: { parameter_keys: ["size"] }, ref: "profile:x" }];
  apiMock.mockRejectedValue(new Error("还有 1 个模型在使用这份参数模板，请先改回跟随目录"));
  render_dialog();

  fireEvent.click(screen.getByLabelText("delete"));

  await waitFor(() =>
    expect(vi.mocked(toast.error)).toHaveBeenCalledWith("还有 1 个模型在使用这份参数模板，请先改回跟随目录"),
  );
});
