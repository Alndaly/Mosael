/** @vitest-environment jsdom */
/**
 * 自定义参数组的**写与删** —— 从用它的那个模型进去。
 *
 * 后端那条链(test_generation_declaration_paths.py)钉住了"声明 → 绑定 → 提交同一份规则";
 * 这里钉入口与表单:用户得真的能在这条连接下建出一份(表单填出来的是什么,POST 的就是什么)、
 * 删掉正在使用的那份时看到 409 那句"还有几个模型在用"。
 *
 * 此前这三条走的是「管理参数组」链接 → 库弹窗 → 编辑器弹窗那条三层路;现在同一件事是模型
 * 设置里选择器的一个分支,所以测试也从**模型设置**进去 —— 那才是用户走的路。
 *
 * 表单结构由后端 schema 端点驱动 —— 这里 mock 一份小 schema,断言**控件跟着 schema 长**,
 * 而不是断言某几个具体字段(那是后端 test_字段集就是保存校验的白名单 的事)。
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (k: string) => k, usePreferences: () => ({ locale: "zh-CN" }) }));

const apiMock = vi.fn();
vi.mock("@/api/client", () => ({ api: (...args: unknown[]) => apiMock(...args) }));

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

/* 与 ModelSettingsDialog.dom.test.tsx 同一个理由:**引用必须稳定**,否则落草稿的 effect 无限重渲染。 */
const SCHEMA = {
  data: {
    parameters: ["size", "num_images", "quality"],
    enum_parameters: ["quality"],
    source_roles: ["reference_image", "first_frame"],
    fields: [
      { key: "parameter_keys", shape: "str_list", group: "params" },
      { key: "sizes", shape: "str_list", group: "choices" },
      { key: "default_size", shape: "str", group: "defaults" },
      { key: "max_num_images", shape: "positive_int", group: "limits" },
    ],
  },
};
const REFS: { data: unknown } = { data: { models: [], profiles: [] } };
const PROFILES: { data: unknown } = { data: [] };
const ROW: { data: unknown } = { data: null };
const EMPTY = { data: [], isLoading: false };

vi.mock("@tanstack/react-query", () => ({
  useQuery: ({ queryKey }: { queryKey: unknown[] }) => {
    const head = (queryKey as string[])[0];
    if (head === "capability-profile-schema") return SCHEMA;
    if (head === "generation-capability-refs") return REFS;
    if (head === "generation-profiles") return PROFILES;
    if (head === "provider-models") return ROW;
    return EMPTY;
  },
  useMutation: ({ mutationFn, onSuccess, onError }: {
    mutationFn: (body: unknown) => Promise<unknown>;
    onSuccess?: (result: unknown) => void;
    onError?: (error: Error) => void;
  }) => ({
    isPending: false,
    mutate: (body: unknown) => mutationFn(body).then((result) => onSuccess?.(result)).catch((error) => onError?.(error)),
  }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));

import { ModelSettingsDialog } from "./ModelSettingsDialog";

const model = (refs: Record<string, string> = {}) => ({
  id: "m", display_name: "", capability_ids: ["image"], effective_capability_ids: ["image"],
  enabled: true, configured: true, in_catalog: true, source: "manual",
  context_window: null, context_window_source: "fallback", max_output_tokens: null,
  reasoning: null, vision: null, reasoning_effort: null, developer_role: null,
  generation_capability_ref: null,
  generation_capability_refs: refs,
  generation_capabilities_known: true,
  generation_capabilities_known_by_kind: { image: true },
});

function open_dialog(refs: Record<string, string> = {}) {
  ROW.data = model(refs);
  return render(
    <ModelSettingsDialog profileId="p1" modelId="m" vendor="openai-compatible" open onOpenChange={() => {}} />,
  );
}

/** 走用户的路:打开选择器,选中那一项。 */
async function pick(name: string) {
  fireEvent.click(screen.getByRole("combobox", { name: "modelGenerationRef" }));
  const item = await screen.findByRole("option", { name });
  fireEvent.click(item);
}

it("新建:名字与表单填出的描述符原样 POST 到这条连接下", async () => {
  apiMock.mockResolvedValue({ id: "x", name: "中转那份", kind: "image", capabilities: {}, ref: "profile:x" });
  open_dialog();

  await pick("modelGenerationRefDescribe");
  fireEvent.change(screen.getByLabelText(/generationProfilesName/), { target: { value: "中转那份" } });
  /* **新建从空白开始。** 旧版预先勾好 size 并塞进 sizes:["1024x1024"] —— 用户一个字没填,
     POST 里已经替这个端点声称了一档尺寸。那正是我们刚从生成界面里拆掉的那种凭空造值。
     勾了什么,描述符才带什么。chips 显示的是翻译键(测试里 i18n 是恒等函数),真机上是人话标签。 */
  fireEvent.click(screen.getByRole("button", { name: "genParam_size" }));
  fireEvent.click(screen.getByRole("button", { name: "genParam_num_images" }));
  fireEvent.click(screen.getByText("save"));

  await waitFor(() => expect(apiMock).toHaveBeenCalled());
  const [url, init] = apiMock.mock.calls[0] as [string, { method: string; body: string }];
  expect(url).toBe("/api/settings/providers/p1/generation-profiles");
  expect(init.method).toBe("POST");
  const body = JSON.parse(init.body);
  expect(body.name).toBe("中转那份");
  expect(body.kind).toBe("image");
  expect(body.capabilities.parameter_keys).toEqual(["size", "num_images"]);
  //: 一档尺寸都没打过 —— 那就一档都不声称,而不是替端点说它支持 1024x1024。
  expect(body.capabilities.sizes ?? []).toEqual([]);
});

it("可选值清单跟着勾出来的参数出现,碎屑编辑器回车加、叉号删", async () => {
  apiMock.mockResolvedValue({ id: "x", ref: "profile:x" });
  open_dialog();

  await pick("modelGenerationRefDescribe");
  //: 勾上 size,尺寸档位清单才出现 —— 没勾的参数不该有它的可选值编辑器。
  expect(screen.queryByLabelText("genField_sizes")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "genParam_size" }));
  const input = screen.getByLabelText("genField_sizes", { selector: "input" });
  fireEvent.change(input, { target: { value: "1536x1024" } });
  fireEvent.keyDown(input, { key: "Enter" });
  /* 按 chip 自己的删除按钮查,不按文字 —— 同一串文字在「默认尺寸」下拉里也有一份,
     按文字查会同时撞到两个,而这里要断言的是清单里那一档。 */
  expect(screen.getByLabelText("genField_sizes 1536x1024")).toBeInTheDocument();
  /* 叉号删得掉 —— 加进去的那一档不是单行道。 */
  fireEvent.change(input, { target: { value: "1024x1024" } });
  fireEvent.keyDown(input, { key: "Enter" });
  fireEvent.click(screen.getByLabelText("genField_sizes 1024x1024"));
  expect(screen.queryByLabelText("genField_sizes 1024x1024")).not.toBeInTheDocument();

  fireEvent.change(screen.getByLabelText(/generationProfilesName/), { target: { value: "x" } });
  fireEvent.click(screen.getByText("save"));
  await waitFor(() => expect(apiMock).toHaveBeenCalled());
  const body = JSON.parse((apiMock.mock.calls[0] as [string, { body: string }])[1].body);
  expect(body.capabilities.sizes).toEqual(["1536x1024"]);
});

it("删除被占用的参数组时,后端那句 409 原样显示在表单里", async () => {
  REFS.data = {
    models: [],
    profiles: [{ value: "profile:x", profile: "中转那份", parameter_keys: ["size"], custom: true, id: "x" }],
  };
  PROFILES.data = [{ id: "x", name: "中转那份", kind: "image", capabilities: { parameter_keys: ["size"] } }];
  apiMock.mockRejectedValue(new Error("还有 1 个模型在使用这份参数模板，请先改回跟随目录"));
  try {
    open_dialog({ image: "profile:x" });
    /* 「编辑这一份」就在选择器底下 —— 删除从用它的那个模型进去,不再有一页独立的管理列表。 */
    fireEvent.click(screen.getByText("modelGenerationRefEditThis"));
    fireEvent.click(screen.getByText("delete"));

    await waitFor(() =>
      expect(screen.getByText("还有 1 个模型在使用这份参数模板，请先改回跟随目录")).toBeInTheDocument(),
    );
  } finally {
    REFS.data = { models: [], profiles: [] };
    PROFILES.data = [];
  }
});
