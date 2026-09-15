/** @vitest-environment jsdom */
/**
 * 自定义参数组的管理对话框与语义化表单。
 *
 * 后端那条链(test_generation_declaration_paths.py)钉住了"声明 → 绑定 → 提交同一份规则";
 * 这里钉它的入口与表单:用户得真的能在这条连接下建出一份(表单填出来的是什么,POST 的就是
 * 什么)、删掉正在使用的模板时看到 409 那句"还有几个模型在用"。
 *
 * 表单结构由后端 schema 端点驱动 —— 这里 mock 一份小 schema,断言**控件跟着 schema 长**,
 * 而不是断言某几个具体字段(那是后端 test_字段集就是保存校验的白名单 的事)。
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
const SCHEMA = {
  data: {
    parameters: ["size", "num_images", "quality"],
    source_roles: ["reference_image", "first_frame"],
    fields: [
      { key: "parameter_keys", shape: "str_list", group: "params" },
      { key: "sizes", shape: "str_list", group: "choices" },
      { key: "default_size", shape: "str", group: "defaults" },
      { key: "max_num_images", shape: "positive_int", group: "limits" },
    ],
  },
};

vi.mock("@tanstack/react-query", () => ({
  useQuery: ({ queryKey }: { queryKey: string[] }) =>
    queryKey[0] === "capability-profile-schema" ? SCHEMA : LIST,
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

it("新建:名字与表单填出的描述符原样 POST 到这条连接下", async () => {
  state.rows = [];
  apiMock.mockResolvedValue({ id: "x", name: "中转那份", kind: "image", capabilities: {}, ref: "profile:x" });
  render_dialog();

  fireEvent.click(screen.getByText("generationProfilesAdd"));
  fireEvent.change(screen.getByLabelText(/generationProfilesName/), { target: { value: "中转那份" } });
  /* 默认模板勾了 size;再勾上 num_images —— 表单里勾了什么,描述符就该带什么。 */
  fireEvent.click(screen.getByRole("button", { name: "num_images" }));
  fireEvent.click(screen.getByText("save"));

  await waitFor(() => expect(apiMock).toHaveBeenCalled());
  const [url, init] = apiMock.mock.calls[0] as [string, { method: string; body: string }];
  expect(url).toBe("/api/settings/providers/p1/generation-profiles");
  expect(init.method).toBe("POST");
  const body = JSON.parse(init.body);
  expect(body.name).toBe("中转那份");
  expect(body.kind).toBe("image");
  expect(body.capabilities.parameter_keys).toEqual(["size", "num_images"]);
  expect(body.capabilities.sizes).toEqual(["1024x1024"]);
});

it("可选值清单跟着勾出来的参数出现,碎屑编辑器回车加、叉号删", async () => {
  state.rows = [];
  render_dialog();

  fireEvent.click(screen.getByText("generationProfilesAdd"));
  /* 默认勾着 size → 尺寸档位清单在;往里面加一个 1536x1024。 */
  const input = screen.getByLabelText("genField_sizes", { selector: "input" });
  fireEvent.change(input, { target: { value: "1536x1024" } });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(screen.getByText("1536x1024")).toBeInTheDocument();
  /* 叉号删回默认那档,清单只剩新加的这个 —— 默认尺寸下拉的可选项跟着清单走。 */
  fireEvent.click(screen.getByLabelText("genField_sizes 1024x1024"));
  expect(screen.queryByText("1024x1024")).not.toBeInTheDocument();

  fireEvent.change(screen.getByLabelText(/generationProfilesName/), { target: { value: "x" } });
  fireEvent.click(screen.getByText("save"));
  await waitFor(() => expect(apiMock).toHaveBeenCalled());
  const body = JSON.parse((apiMock.mock.calls[0] as [string, { body: string }])[1].body);
  expect(body.capabilities.sizes).toEqual(["1536x1024"]);
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
