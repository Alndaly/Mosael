/** @vitest-environment jsdom */
/**
 * 模型设置弹窗的**分组**。
 *
 * 这一屏一度是四段平级:能力 / 上下文长度 / 高级 / 生成参数,同样的标题字号摆在一起,
 * 读者得自己在脑子里划分组 —— 而它们不是同一类东西:能力决定后面出现什么,上下文和高级属于
 * 对话,参数来源属于生成。
 *
 * 判据是**分组随能力增删**:纯对话模型不该看见生成那一组,纯生成模型不该看见上下文和高级。
 * 这比断言字号耐久 —— 字号会调,而"这一组属于哪种能力"是结构。
 */
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (k: string) => k, usePreferences: () => ({ locale: "zh-CN" }) }));
vi.mock("@/api/client", () => ({ api: vi.fn(async () => ({ models: [], profiles: [] })) }));

const model = (capabilities: string[], known = true, refs: Record<string, string> = {}) => ({
  id: "m", display_name: "", capability_ids: capabilities, effective_capability_ids: capabilities,
  enabled: true, configured: true, in_catalog: true, source: "manual",
  context_window: null, context_window_source: "fallback", max_output_tokens: null,
  reasoning: null, vision: null, reasoning_effort: null, developer_role: null,
  generation_capability_ref: null,
  /* 声明按 (模型, kind) 分行 —— 双能力模型的两个 kind 各指各的(ADR-0013)。 */
  generation_capability_refs: refs,
  generation_capabilities_known: known,
  generation_capabilities_known_by_kind: Object.fromEntries(
    capabilities.filter((one) => one === "image" || one === "video").map((one) => [one, known]),
  ),
});

/* **引用必须稳定。** 每次渲染返回一个新数组/新对象,组件里那条"把查询结果落成草稿"的 effect
   就会每次都判定为变了 —— 无限重渲染,直接把 worker 撑爆(第一版就是这么 OOM 的)。 */
type RefOption = { value: string; profile: string; parameter_keys: string[]; custom?: boolean; id?: string };
const REFS: { data: { models: unknown[]; profiles: RefOption[] } } = { data: { models: [], profiles: [] } };
const EMPTY = { data: [], isLoading: false };
/* 组件用 `select` 从整份列表里挑出这一行 —— mock 也得走同一条路,直接把数组当 data 返回
   等于跳过了它,弹窗拿到的是数组而不是那一行,整个内容渲染不出来。 */
const state: { row: unknown } = { row: null };
const ROW = { data: null as unknown, isLoading: false };

vi.mock("@tanstack/react-query", () => ({
  useQuery: ({ queryKey }: { queryKey: unknown[] }) =>
    (queryKey as string[])[0] === "generation-capability-refs" ? REFS
      : (queryKey as string[])[0] === "provider-models" ? ROW : EMPTY,
  useMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));

import { ModelSettingsDialog } from "./ModelSettingsDialog";

function open(capabilities: string[], known = true, refs: Record<string, string> = {}) {
  state.row = model(capabilities, known, refs);
  ROW.data = state.row;
  return render(
    <ModelSettingsDialog profileId="p" modelId="m" vendor="openai-compatible" open onOpenChange={() => {}} />,
  );
}

it("纯对话模型看不到生成那一组", () => {
  open(["chat"]);
  expect(screen.getByText("modelSettingsChatGroup")).toBeInTheDocument();
  expect(screen.queryByText("modelSettingsGenerationGroup")).not.toBeInTheDocument();
});

it("纯生成模型看不到对话那一组 —— 它没有上下文窗口,也不认 developer 角色", () => {
  open(["image"]);
  expect(screen.getByText("modelSettingsGenerationGroup")).toBeInTheDocument();
  expect(screen.queryByText("modelSettingsChatGroup")).not.toBeInTheDocument();
});

it("两种能力都有时两组都在", () => {
  open(["chat", "image"]);
  expect(screen.getByText("modelSettingsChatGroup")).toBeInTheDocument();
  expect(screen.getByText("modelSettingsGenerationGroup")).toBeInTheDocument();
});

it("双生成能力的模型,「生成」组头只说一遍,kind 缀在字段名后面区分", () => {
  /* 此前逐 kind 渲染整组:两个一模一样的「生成」标题、两条分隔线摞在一起,
     间距也成双 —— 同一件事说了两遍。 */
  open(["image", "video"]);
  expect(screen.getAllByText("modelSettingsGenerationGroup")).toHaveLength(1);
  expect(screen.getByText("image")).toBeInTheDocument();
  expect(screen.getByText("video")).toBeInTheDocument();
  expect(screen.getAllByRole("combobox", { name: "modelGenerationRef" })).toHaveLength(2);
});

it("同一件事只说一遍:认不出参数时才有那句解释,而且只有一句", () => {
  const { unmount } = open(["image"], false);
  expect(screen.getByText("modelGenerationRefUnknown")).toBeInTheDocument();
  unmount();
  // 认得出来的时候不该还挂着一段常驻说明 —— 它此前和这句黄字讲的是同一件事。
  open(["image"], true);
  expect(screen.queryByText("modelGenerationRefUnknown")).not.toBeInTheDocument();
  expect(screen.queryByText("modelGenerationRefHint")).not.toBeInTheDocument();
});

it("双能力模型的两个 kind 各有一个选择器 —— 共用一个引用就是只能配置一半", () => {
  open(["image", "video"]);
  expect(screen.getAllByRole("combobox", { name: "modelGenerationRef" })).toHaveLength(2);
});

it("这条连接的自定义参数组出现在选择器里", async () => {
  REFS.data = {
    models: [],
    profiles: [{ value: "profile:abc", profile: "中转那份", parameter_keys: ["size", "num_images"], custom: true, id: "abc" }],
  };
  try {
    open(["image"]);
    fireEvent.click(screen.getByRole("combobox", { name: "modelGenerationRef" }));
    /* i18n 在测试里是恒等函数,名字拼不进 label;能断言的是参数清单那行描述 ——
       它回答的是"选它会得到哪几项"。 */
    expect(await screen.findByText("size · num_images")).toBeInTheDocument();
  } finally {
    REFS.data = { models: [], profiles: [] };
  }
});

it("「自己描述这个端点」是字段下面的一个动作,不是选择器里的一个取值", async () => {
  /* 选择器里该只有能**选中**的值(自动识别、和某个模型一样、某个参数组)。把这个动作混进去
     之后,它既像一个取值,又要在选中的瞬间把整个对话框换掉 —— 而"选一个值"和"打开一个编辑器"
     是两件事。(更早的一版更远:它是「管理参数组」链接 → 库弹窗 → 编辑器弹窗,三层叠着。) */
  open(["image"]);
  expect(screen.getByText("modelGenerationRefDescribe")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("combobox", { name: "modelGenerationRef" }));
  await screen.findByRole("option", { name: /modelGenerationRefFollow/ });
  expect(screen.queryByRole("option", { name: "modelGenerationRefDescribe" })).not.toBeInTheDocument();
});

it("「自动识别」说得出它会做什么 —— 「跟随目录」是我们的行话", async () => {
  //: 这一格问的是"参数按什么来",而"跟随目录"既没说会发生什么,也没说"目录"是什么。
  open(["image"]);
  fireEvent.click(screen.getByRole("combobox", { name: "modelGenerationRef" }));
  expect(await screen.findByText("modelGenerationRefFollowHint")).toBeInTheDocument();
});

it("「编辑这一份」只在选中的是自己建的那种时出现", () => {
  // 内置档案是我们查证过的事实,不是用户的断言 —— 给它一个编辑入口是在说谎。
  REFS.data = {
    models: [],
    profiles: [
      { value: "profile:openai-image", profile: "openai-image", parameter_keys: ["size"], custom: false },
      { value: "profile:abc", profile: "我的", parameter_keys: ["size"], custom: true, id: "abc" },
    ],
  };
  try {
    open(["image"], true, { image: "profile:openai-image" });
    expect(screen.queryByText("modelGenerationRefEditThis")).not.toBeInTheDocument();
  } finally {
    REFS.data = { models: [], profiles: [] };
  }
});
