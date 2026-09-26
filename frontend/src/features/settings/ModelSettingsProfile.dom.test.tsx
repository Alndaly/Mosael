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
    //: 「这个参数的可选值装在哪个键里」由后端给 —— 界面不再自己攒这张表(见 _CHOICES_KEY)。
    choices_key: { size: "sizes" },
    fields: [
      { key: "parameter_keys", shape: "str_list", group: "params" },
      { key: "sizes", shape: "str_list", group: "choices" },
      //: defaults 组的每一格都说得出自己是**谁的**默认值,界面据此决定要不要摆这一行。
      { key: "default_size", shape: "str", group: "defaults", defaults_for: "size" },
      { key: "default_quality", shape: "str", group: "defaults", defaults_for: "quality" },
      { key: "max_num_images", shape: "positive_int", group: "limits" },
      //: 必需素材那种形状 —— 一行是"一组素材角色",而空的一组在描述符里存不下。
      { key: "requires_source", shape: "str_list_list", group: "advanced" },
      //: 三选一的一格(提示词要不要写):可选值由后端随表单结构给,界面不再抄一份。
      { key: "prompt", shape: "choice", group: "advanced", choices: ["required", "optional", "none"] },
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

/** 走用户的路:点字段下面那个动作。
    它不在选择器里 —— 选择器里只有能选的**值**,「自己描述这个端点」是一个动作。 */
function describe_endpoint() {
  fireEvent.click(screen.getByText("modelGenerationRefDescribe"));
}

it("新建:名字与表单填出的描述符原样 POST 到这条连接下", async () => {
  apiMock.mockResolvedValue({ id: "x", name: "中转那份", kind: "image", capabilities: {}, ref: "profile:x" });
  open_dialog();

  describe_endpoint();
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

  describe_endpoint();
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

it("「加一行」真的加得出一行 —— 还没起名的那一行也得留得住", async () => {
  /* 真机上点它什么都不发生:行列表是从描述符**推导**出来的(Object.entries(value[key])),
     而刚加的那一行还没有名字,提交时被 name.trim() 过滤掉 —— 描述符没变,重渲染推导出的
     还是原来那几行。不是按钮没绑事件,是草稿放在了一个存不下草稿的地方。 */
  open_dialog();
  describe_endpoint();
  //: parameter_choices 那一格只在勾了"真有枚举值"的参数之后才出现(这份 schema 里是 quality)。
  fireEvent.click(screen.getByRole("button", { name: "genParam_quality" }));
  /* 名字那一列是个**选择器**(候选是封闭集合),按 combobox 角色找:同一个 aria-label
     还挂在这一行的碎屑编辑器上(它的标签是 `${名字列} ${行名}`,行名为空时归一化后一模一样)。 */
  const nameCell = () => screen.queryAllByRole("combobox", { name: "genField_parameter_choices" });
  expect(nameCell()).toHaveLength(0);

  fireEvent.click(screen.getByText("genFormAddRow"));
  expect(nameCell()).toHaveLength(1);

  //: 起了名字才算数 —— 而"算数"的判据是它**真的进了描述符**,不是界面上还画着。
  apiMock.mockResolvedValue({ id: "x", ref: "profile:x" });
  fireEvent.click(nameCell()[0]);
  fireEvent.click(await screen.findByRole("option", { name: "quality" }));
  const chips = screen.getByLabelText("genField_parameter_choices quality");
  fireEvent.change(chips, { target: { value: "hd" } });
  fireEvent.keyDown(chips, { key: "Enter" });

  fireEvent.change(screen.getByLabelText(/generationProfilesName/), { target: { value: "x" } });
  fireEvent.click(screen.getByText("save"));
  await waitFor(() => expect(apiMock).toHaveBeenCalled());
  const body = JSON.parse((apiMock.mock.calls[0] as [string, { body: string }])[1].body);
  expect(body.capabilities.parameter_choices).toEqual({ quality: ["hd"] });
});

it("点「加一行」不会把这一整格弄没 —— 「打开了」和「有值」是两件事", async () => {
  /* 真机上撞到的:在「必需素材」里点「加一行」,整格连标题一起消失了。
     那一格是"一组一组的素材角色"(str_list_list),刚加的那一组还是空的,提交时被
     `filter(group.length)` 滤光 —— 于是 unset(key),而这一格是否渲染正是看 key 在不在。
     用户点的是"加一行",看到的是"这一项没了"。 */
  open_dialog();
  describe_endpoint();
  /* 两个「添加字段」:「上限」一个、「特殊规则」一个。合成一组时,「必需素材」「支持音频」
     这些既不是上限也说不上高级的字段全落在一个说不着它们的标题底下。 */
  const adders = screen.getAllByRole("combobox", { name: "genFormAddField" });
  expect(adders).toHaveLength(2);
  fireEvent.click(adders[1]);
  fireEvent.click(await screen.findByRole("option", { name: "genField_requires_source" }));
  expect(screen.getByText("genField_requires_source")).toBeInTheDocument();

  //: 这一格里也有一个「加一行」—— 点它之后这一格得还在。
  const addRow = screen.getAllByText("genFormAddRow");
  fireEvent.click(addRow[addRow.length - 1]);
  expect(screen.getByText("genField_requires_source")).toBeInTheDocument();

  //: 只有那个 × 才关得掉它。
  fireEvent.click(screen.getByLabelText("genField_requires_source genFormRemoveField"));
  expect(screen.queryByText("genField_requires_source")).not.toBeInTheDocument();
});

it("每一组都说得出自己和别的组差在哪", () => {
  /* 「可调参数」「可选值」「默认值」「上限」「特殊规则」—— 标题都是两三个字,光看标题分不出
     各管什么,而它们回答的是几个不同的问题:摆哪几个旋钮、每个旋钮有哪几档、一开始停在哪档、
     硬限制是什么、请求形状上有什么怪脾气。真机上的提问就是「上限和高级与上面的有什么区别」。 */
  open_dialog();
  describe_endpoint();
  fireEvent.click(screen.getByRole("button", { name: "genParam_size" }));
  //: 「默认值」那一组要有一档可选值才出现 —— 没有清单就没有"默认停在哪一档"可言。
  const sizes = screen.getByLabelText("genField_sizes", { selector: "input" });
  fireEvent.change(sizes, { target: { value: "1024x1024" } });
  fireEvent.keyDown(sizes, { key: "Enter" });
  for (const group of ["choices", "defaults", "limits", "advanced"]) {
    expect(screen.getByText(`genGroupHint_${group}`)).toBeInTheDocument();
  }
});

it("有档位的旋钮都配得上默认值 —— 不是只有尺寸那几个", async () => {
  /* 用户问的是"有些需要设置默认值,有些不需要?"。当时的答案是"界面自己攒了一张名单",
     名单上只有 size / resolution / aspect_ratio / duration 和两个开关 —— 于是给 quality
     声明完可选值之后,没有任何地方可以设 default_quality,而后端一直收这个键。
     现在这一组跟着勾出来的旋钮长,"这一格是谁的默认值"由 schema 说(defaults_for)。 */
  open_dialog();
  describe_endpoint();
  fireEvent.click(screen.getByRole("button", { name: "genParam_quality" }));
  //: 还没声明取值时不摆 —— 一个点开是空的下拉,比没有它更糟。
  expect(screen.queryByText("genField_default_quality")).not.toBeInTheDocument();

  fireEvent.click(screen.getByText("genFormAddRow"));
  fireEvent.click(screen.getAllByRole("combobox", { name: "genField_parameter_choices" })[0]);
  fireEvent.click(await screen.findByRole("option", { name: "quality" }));
  const chips = screen.getByLabelText("genField_parameter_choices quality");
  fireEvent.change(chips, { target: { value: "hd" } });
  fireEvent.keyDown(chips, { key: "Enter" });

  //: 有档位了,这一格就该出现,而且只能从声明过的那几档里选。
  expect(screen.getByText("genField_default_quality")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("combobox", { name: "genField_default_quality" }));
  expect(await screen.findByRole("option", { name: "hd" })).toBeInTheDocument();
});

it("旋钮取消勾选之后,它那一格默认值跟着消失", () => {
  /* 档位清单还留着(用户可能只是手滑),但"这个旋钮一开始停在哪一档"已经无从谈起 ——
     一个不存在的旋钮的默认值,保存下去就是描述符里一条永远不会被读到的声明。 */
  open_dialog();
  describe_endpoint();
  fireEvent.click(screen.getByRole("button", { name: "genParam_size" }));
  const sizes = screen.getByLabelText("genField_sizes", { selector: "input" });
  fireEvent.change(sizes, { target: { value: "1024x1024" } });
  fireEvent.keyDown(sizes, { key: "Enter" });
  expect(screen.getByText("genField_default_size")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "genParam_size" }));
  expect(screen.queryByText("genField_default_size")).not.toBeInTheDocument();
});

it("三选一的一格:可选值来自表单结构,打开时从「可以不写」开始,选了什么就存什么", async () => {
  apiMock.mockResolvedValue({ id: "x", ref: "profile:x" });
  open_dialog();
  describe_endpoint();
  const adders = screen.getAllByRole("combobox", { name: "genFormAddField" });
  fireEvent.click(adders[1]);
  fireEvent.click(await screen.findByRole("option", { name: "genField_prompt" }));
  const picker = screen.getByRole("combobox", { name: "genField_prompt" });
  expect(picker).toHaveTextContent("genField_prompt_optional");
  fireEvent.click(picker);
  fireEvent.click(await screen.findByRole("option", { name: "genField_prompt_none" }));

  fireEvent.change(screen.getByLabelText(/generationProfilesName/), { target: { value: "放大" } });
  fireEvent.click(screen.getByText("save"));
  await waitFor(() => expect(apiMock).toHaveBeenCalled());
  const body = JSON.parse((apiMock.mock.calls[0] as [string, { body: string }])[1].body);
  expect(body.capabilities.prompt).toBe("none");
});
