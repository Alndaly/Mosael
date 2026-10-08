/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 生成工作台的两件事:
 *
 * - 同事**共享来的**会话只能看(后端 generation/sessions 定的,`is_mine: false` 是它给的答案):输入区换成一句
 *   只读说明,模型与参数栏不开、也不会把模型 PATCH 到别人的会话上;左栏那一行没有右键菜单、选不进批量删。
 * - 失败卡读**生成记录自己**存的失败原因:任务被「清空已结束」删掉之后(job_id 为空、任务列表里没有它),
 *   原因还在。
 */

//: 文案键原样回;两层名字的副名(ADR 0045)那两句给真话,断言才读得出「来自 X」
vi.mock("@/app/preferences", () => {
  const said: Record<string, string> = { entryFromGroup: "来自 {name}", entryFullWorkflow: "完整工作流" };
  return {
    useI18n: () => (key: string) => said[key] ?? key,
    usePreferences: () => ({ locale: "zh-CN" }),
  };
});

import { AiStudio } from "@/features/ai-studio/AiStudio";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { hoverHint, readHint } from "@/test/hint";

beforeAll(() => {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as never;
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  });
});
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});
beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("mosael:tab:ai-studio", "create");
  //: 上次开着的是 s1(没选过会话时停在「新的一条」,不落进最近那条,见 UC-03)
  localStorage.setItem("mosael.generation.session.w1.create", "s1");
});

const IMAGE_OPTION = {
  id: "p1:image:gpt-image-1",
  provider_profile_id: "p1",
  profile_name: "OpenAI",
  provider: "openai",
  kind: "image",
  model: "gpt-image-1",
  model_label: "gpt-image-1",
  label: "OpenAI · gpt-image-1",
  capabilities: { modes: ["text-to-image"], parameter_keys: [] },
  capabilities_known: true,
  adapter_available: true,
  is_default: true,
};

function session(isMine: boolean) {
  return {
    id: "s1",
    workspace_id: "w1",
    title: "同事的海报",
    kind: "image",
    provider_profile_id: "their-profile",
    model: "gpt-image-1",
    is_mine: isMine,
    shared: true,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
  };
}

//: 记着的模型不在选项里时,后端说它叫什么、为什么(GET /api/generation/missing);缺省是「连接删了」那一句
const GONE = { provider_profile_id: "gone", model: "krea2-text-2-image.json#app", model_label: "之前选的模型", profile_name: "",
               group: null, reason: "它所在的那条连接已经删掉了", upgrade: false, plugin_instance_id: "" };

function renderStudio({ isMine = true, generations = [] as unknown[], options = [IMAGE_OPTION] as unknown[],
                        sessions = [session(isMine)] as unknown[], missing = GONE as unknown } = {}) {
  const writes: Array<{ url: string; method: string; body?: unknown }> = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    if (init?.method && init.method !== "GET") {
      writes.push({ url, method: init.method, body: init.body ? JSON.parse(String(init.body)) : undefined });
      return json(url.endsWith("/api/generation/sessions") ? { id: "s-new" } : {});
    }
    if (url.includes("/api/generation/options?kind=image")) return json(options);
    if (url.includes("/api/generation/options")) return json([]);
    if (url.includes("/api/generation/missing")) return json(missing);
    if (url.includes("/api/generation/sessions")) return json(sessions);
    if (url.includes("/api/generation/jobs")) return json(generations);
    return json([]);
  }) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ImagePreviewProvider>
        <AiStudio workspace={{ id: "w1", name: "W" } as never} />
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
  return { writes };
}

describe("共享来的会话只能看", () => {
  it("输入区换成只读说明,模型与参数栏不开", async () => {
    renderStudio({ isMine: false });
    expect(await screen.findByRole("note")).toHaveTextContent("generationSessionReadOnly");
    expect(screen.queryByRole("textbox", { name: "genPromptLabel" })).toBeNull();
    expect(screen.queryByRole("button", { name: "generate" })).toBeNull();
    expect(screen.queryByRole("button", { name: "generationEngineSettings" })).toBeNull();
    // 参数栏收起(测试环境不加载样式表,看的是它挂着 hidden)。
    expect(screen.getByRole("complementary", { name: "generationEngineSettings", hidden: true })).toHaveClass("hidden");
  });

  it("左栏那一行没有右键菜单(改名、收纳、删除都是主人的事),也选不进批量删", async () => {
    const { writes } = renderStudio({ isMine: false });
    const row = await screen.findByRole("button", { name: /同事的海报/ });
    expect(await readHint(row)).toContain("generationSessionReadOnly");
    fireEvent.contextMenu(row);
    expect(screen.queryByRole("menuitem", { name: /rename/ })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /delete/ })).toBeNull();
    // 能管的一条都没有:多选进不去。
    expect(screen.getByRole("button", { name: "mediaSelectMode" })).toBeDisabled();
    expect(writes).toEqual([]);
  });

  it("自己的会话照旧:有输入框、有参数栏、右键能改名", async () => {
    renderStudio({ isMine: true });
    expect(await screen.findByRole("textbox", { name: "genPromptLabel" })).toBeInTheDocument();
    expect(screen.queryByRole("note")).toBeNull();
    expect(screen.getByRole("complementary", { name: "generationEngineSettings" })).not.toHaveClass("hidden");
    const row = await screen.findByRole("button", { name: /同事的海报/ });
    fireEvent.contextMenu(row);
    expect(await screen.findByRole("menuitem", { name: /rename/ })).toBeInTheDocument();
  });
});

describe("失败原因读生成记录自己的", () => {
  it("任务已经被清掉:照样说得出为什么失败", async () => {
    renderStudio({
      generations: [
        {
          id: "g1",
          workspace_id: "w1",
          session_id: "s1",
          job_id: null,
          provider_profile_id: "p1",
          provider: "openai",
          model: "gpt-image-1",
          kind: "image",
          request: { prompt: "一张海报" },
          result_asset_id: null,
          result_asset_ids: [],
          error: "供应商 openai 还没有配置你的密钥,请先在设置里填写",
          error_summary: "供应商 openai 还没有配置你的密钥,请先在设置里填写",
          created_at: "2026-09-01T00:00:00Z",
          updated_at: "2026-09-01T00:01:00Z",
          costs: [],
          cost_confidence: null,
        },
      ],
    });
    expect(await screen.findByText("generationFailedTitle")).toBeInTheDocument();
    expect(screen.getAllByText("供应商 openai 还没有配置你的密钥,请先在设置里填写").length).toBeGreaterThan(0);
    expect(screen.queryByText("genFailed")).toBeNull();
    // 用户气泡只画他说的话。
    expect(screen.getByText("一张海报")).toBeInTheDocument();
  });

  it("记录上没有原因的老记录:说「生成失败」,不猜", async () => {
    renderStudio({
      generations: [
        {
          id: "g1",
          workspace_id: "w1",
          session_id: "s1",
          job_id: null,
          provider: "openai",
          model: "gpt-image-1",
          kind: "image",
          request: { prompt: "一张海报" },
          result_asset_id: null,
          result_asset_ids: [],
          error: null,
          created_at: "2026-09-01T00:00:00Z",
          updated_at: "2026-09-01T00:01:00Z",
          costs: [],
          cost_confidence: null,
        },
      ],
    });
    await waitFor(() => expect(screen.getByText("genFailed")).toBeInTheDocument());
  });
});

describe("失败卡写后端那一句人话,原文收在折起的「详情」里(UC-06,维护者 2026-10-08 重构)", () => {
  const failed = (extra: Record<string, unknown>) => ({
    id: "g1", workspace_id: "w1", session_id: "s1", job_id: "j1", provider_profile_id: "p1", provider: "alibaba",
    model: "wanx", kind: "image", request: { prompt: "一只猫" }, result_asset_id: null, result_asset_ids: [],
    error: "DashScope 请求失败:Client error '401 Unauthorized' for url 'https://dashscope.aliyuncs.com/api/v1/x?Signature=SECRET'\nFor more information check: https://developer.mozilla.org/401",
    error_summary: "DashScope 不认这把密钥,请到设置里检查连接的凭据:Invalid API-key provided.",
    error_detail: "Client error '401 Unauthorized' for url 'https://dashscope.aliyuncs.com/api/v1/x?Signature=SECRET'\nFor more information check: https://developer.mozilla.org/401",
    error_hint: null,
    created_at: "2026-10-06T00:00:00Z", updated_at: "2026-10-06T00:00:11Z", costs: [], cost_confidence: null,
    retrievable: false, repeatable: true, ...extra,
  });
  //: 维护者截图里那一条:ComfyUI 报了执行错误(远端明确失败)。后端给的一句话、原话、认得出的原因
  const comfy = (extra: Record<string, unknown>) => failed({
    provider_profile_id: "p9", provider: "plugin:dev.mosael.comfyui", model: "krea2-text-2-image.json#app",
    error: "「ComfyUI · http://192.168.3.15:8188」生成失败:ComfyUI 执行失败:KSampler: hostbuf_file_reader_read failed",
    error_summary: "ComfyUI 执行到「KSampler」这一步出错",
    error_detail: "KSampler: hostbuf_file_reader_read failed",
    error_hint: "这是那台 ComfyUI 上的问题,不是这张工作流的:它装的 comfy-kitchen 太旧……",
    ...extra,
  });

  it("卡上写那一句,不写原文;原文在默认折起的「详情」里,复制在详情里", async () => {
    renderStudio({ generations: [failed({})] });
    const card = (await screen.findByText("generationFailedTitle")).closest("[data-generation-failed]") as HTMLElement;
    expect(card.textContent).toContain("DashScope 不认这把密钥");
    const shown = within(card).getByText(/DashScope 不认这把密钥/);
    expect(shown.textContent).not.toMatch(/https?:|For more information|SECRET/);
    const details = card.querySelector<HTMLDetailsElement>("[data-failure-detail]")!;
    expect(details.open, "默认折起").toBe(false);
    expect(within(details).getByText("genFailureDetail")).toBeInTheDocument();
    expect(details.querySelector("pre")?.textContent).toContain("For more information check");
    expect(details.querySelector("[data-failure-copy]"), "有详情时复制在详情里").not.toBeNull();
    expect(card.querySelector("[data-failure-actions] [data-failure-copy]"), "动作那一排不再摆一颗").toBeNull();
  });

  it("ComfyUI 报了执行错误:不摆「重新取回」;一句人话不重复连接名;认得出的原因给提示;能再来一次;没写字不摆空气泡", async () => {
    renderStudio({ generations: [comfy({ request: { prompt: "" } })], options: [IMAGE_OPTION, { ...IMAGE_OPTION, id: "p9:image:krea2", provider_profile_id: "p9",
      provider: "plugin:dev.mosael.comfyui", model: "krea2-text-2-image.json#app", model_label: "快速用krea2生图", is_default: false }] });
    const card = (await screen.findByText("generationFailedTitle")).closest("[data-generation-failed]") as HTMLElement;
    expect(within(card).queryByRole("button", { name: /genRetrieve/ })).toBeNull();
    const said = card.querySelector("[data-failure-summary]")!.textContent!;
    expect(said).toBe("ComfyUI 执行到「KSampler」这一步出错");
    expect(said).not.toContain("生成失败");
    expect(card.querySelector("[data-failure-hint]")?.textContent).toContain("这是那台 ComfyUI 上的问题");
    expect(within(card).getByRole("button", { name: /genRepeat/ })).toBeInTheDocument();
    expect(card.querySelector("[data-failure-detail] pre")?.textContent).toBe("KSampler: hostbuf_file_reader_read failed");
    const turn = card.closest("article")!;
    expect(turn.querySelector("[data-generation-prompt]"), "这一轮没写字:不摆空气泡").toBeNull();
    expect(within(turn as HTMLElement).queryByRole("button", { name: "复制" }), "也没有空的「复制」").toBeNull();
  });

  it("原文和那一句说的是同一件事(后端不给详情):不摆「详情」,「复制错误」在动作那一排", async () => {
    renderStudio({ generations: [failed({ error: "ComfyUI 里这个任务被中断了", error_summary: "ComfyUI 里这个任务被中断了",
                                          error_detail: null })] });
    const card = (await screen.findByText("generationFailedTitle")).closest("[data-generation-failed]") as HTMLElement;
    expect(card.querySelector("[data-failure-detail]")).toBeNull();
    expect(within(card).queryByText("genFailureDetail")).toBeNull();
    expect(card.querySelector("[data-failure-actions] [data-failure-copy]")?.textContent).toContain("genCopyError");
  });

  it("颜色克制:只有标题用 destructive 色,那一句是正常前景色,底是中性面板色", async () => {
    renderStudio({ generations: [failed({})] });
    const card = (await screen.findByText("generationFailedTitle")).closest("[data-generation-failed]") as HTMLElement;
    expect(card.className).not.toMatch(/destructive/);
    expect(card.className).toMatch(/bg-secondary/);
    expect(card.querySelector("[data-failure-summary]")!.className).toMatch(/text-foreground/);
    expect(card.querySelector("[data-failure-summary]")!.className).not.toMatch(/destructive/);
    expect(card.getAttribute("role")).toBe("group");
    expect(document.getElementById(card.getAttribute("aria-labelledby")!)?.textContent).toBe("generationFailedTitle");
  });

  it("记着的模型用不了、修法是升级:失败卡上给「去工作流库升级」,不给「再来一次」", async () => {
    renderStudio({ generations: [comfy({})], missing: { ...GONE, provider_profile_id: "p9", model: "krea2-text-2-image.json#app",
                                                        model_label: "krea2-text-2-image 的表单", upgrade: true,
                                                        plugin_instance_id: "inst9", reason: "表单还是旧格式" } });
    const card = (await screen.findByText("generationFailedTitle")).closest("[data-generation-failed]") as HTMLElement;
    await waitFor(() => expect(within(card).getByRole("button", { name: "genModelMissingUpgrade" })).toBeInTheDocument());
    expect(within(card).queryByRole("button", { name: /genRepeat/ })).toBeNull();
  });

  it("再来一次:发 /again,不发新的生成请求体", async () => {
    //: 记着的模型还在选项里才摆(用不了的给「去工作流库升级」)
    const { writes } = renderStudio({ generations: [failed({ provider: "openai", model: "gpt-image-1" })] });
    fireEvent.click(await screen.findByRole("button", { name: /genRepeat/ }));
    await waitFor(() => expect(writes.some((one) => one.url.endsWith("/api/generation/jobs/g1/again"))).toBe(true));
    expect(writes.some((one) => one.url.endsWith("/api/generation/jobs"))).toBe(false);
  });

  it("不能照原样再来的(工作台画布、数字人)、记着的模型用不了的:不摆「再来一次」", async () => {
    renderStudio({ generations: [failed({ provider: "openai", model: "gpt-image-1", repeatable: false })] });
    await screen.findByText("generationFailedTitle");
    expect(screen.queryByRole("button", { name: /genRepeat/ })).toBeNull();
    cleanup();
    renderStudio({ generations: [failed({ model: "gone-model" })] });
    await screen.findByText("generationFailedTitle");
    expect(screen.queryByRole("button", { name: /genRepeat/ }), "模型不在了").toBeNull();
  });

  it("服务商做完了、成片没拿回来的:摆「重新取回」,点了发重新取回,不重新生成", async () => {
    const { writes } = renderStudio({ generations: [failed({ retrievable: true })] });
    fireEvent.click(await screen.findByRole("button", { name: /genRetrieve/ }));
    await waitFor(() => expect(writes).toContainEqual(expect.objectContaining({ url: expect.stringContaining("/api/generation/jobs/g1/retrieve"), method: "POST" })));
    expect(writes.some((one) => one.url.endsWith("/api/generation/jobs"))).toBe(false);
  });

  it("取不回的(没提交出去、被停下、同步接口):不摆「重新取回」", async () => {
    renderStudio({ generations: [failed({ retrievable: false })] });
    await screen.findByText("generationFailedTitle");
    expect(screen.queryByRole("button", { name: /genRetrieve/ })).toBeNull();
  });
});

describe("花费那一句照实说:花了多少 / 未定价 / 未扣费", () => {
  const generation = (id: string, prompt: string, extra: Record<string, unknown>) => ({
    id, workspace_id: "w1", session_id: "s1", job_id: null, provider: "plugin:dev.mosael.comfyui", model: "girl.json",
    kind: "image", request: { prompt }, result_asset_id: null, result_asset_ids: [], error: null,
    created_at: "2026-10-06T00:00:00Z", updated_at: "2026-10-06T00:00:11Z", ...extra,
  });

  //: 沙盒实测:本机 ComfyUI 没配价,成功的那次「未定价」、失败的那次「费用 US$0.00」—— 失败了没扣钱不是一笔 $0
  it("成功了没价说「未定价」;失败了没扣钱说「未扣费」,不说「费用 US$0.00」;有价的照金额", async () => {
    renderStudio({
      generations: [
        generation("g1", "成功没价", { result_asset_id: "a1", result_asset_ids: ["a1"], costs: [], cost_confidence: "unknown" }),
        generation("g2", "失败没扣", { error: "Prompt outputs failed validation", costs: [], cost_confidence: "not_billed" }),
        generation("g3", "成功有价", { result_asset_id: "a3", result_asset_ids: ["a3"],
                                     costs: [{ currency: "CNY", micros: 250_000 }], cost_confidence: "estimated" }),
      ],
    });
    const footer = async (prompt: string) =>
      (await screen.findAllByText(prompt)).map((one) => one.closest("article")!).find(Boolean)!;
    expect((await footer("成功没价")).textContent).toContain("usageCostUnknown");
    const failed = await footer("失败没扣");
    expect(failed.textContent).toContain("usageCostNotBilled");
    expect(failed.textContent).not.toMatch(/usageCost[^NU]|\$0/);
    expect((await footer("成功有价")).textContent).toContain("usageCost");
    expect((await footer("成功有价")).textContent).not.toContain("usageCostNotBilled");
  });
});

describe("每一条生成下面写的是给人看的名字", () => {
  //: 维护者:用精简表单「快速用krea2生图」生成,下面却写着「plugin:dev.mosael.comfyui · krea2-text-2-image.json」
  it("脚注写主名(表单标题),悬停写副名(来自哪张工作流、哪台服务器);不写供应商 id 和文件名;连接没了写人话,不露编号", async () => {
    //: ADR 0045:名字分两层,一行的地方写主名,副名进悬停说明 —— 不拼成「连接名 · 工作流名 · 表单名」
    const group = { id: "krea2-text-2-image.json", label: "krea2-text-2-image" };
    const comfy = { ...IMAGE_OPTION, id: "p9:image:krea2-text-2-image.json#app", provider_profile_id: "p9",
                    profile_name: "ComfyUI · http://192.168.3.15:8188", provider: "plugin:dev.mosael.comfyui",
                    model: "krea2-text-2-image.json#app", model_label: "快速用krea2生图", group: { ...group, entry: "form" },
                    is_default: false };
    const full = { ...comfy, id: "p9:image:krea2-text-2-image.json", model: "krea2-text-2-image.json",
                   model_label: "krea2-text-2-image", group: { ...group, entry: "full" } };
    const record = (id: string, prompt: string, profile: string) => ({
      id, workspace_id: "w1", session_id: "s1", job_id: null, provider_profile_id: profile, provider: "plugin:dev.mosael.comfyui",
      model: "krea2-text-2-image.json#app", kind: "image", request: { prompt }, result_asset_id: "a1", result_asset_ids: ["a1"],
      error: null, created_at: "2026-10-06T00:00:00Z", updated_at: "2026-10-06T00:00:11Z",
    });
    renderStudio({ options: [IMAGE_OPTION, full, comfy], generations: [record("g1", "连接还在", "p9"), record("g2", "连接删了", "gone")] });
    const footer = async (prompt: string) =>
      (await screen.findAllByText(prompt)).map((one) => one.closest("article")!).find(Boolean)!;
    const named = await footer("连接还在");
    await waitFor(() => expect(named.querySelector("[data-engine-name]")?.textContent).toBe("快速用krea2生图"));
    expect(named.textContent).not.toContain("plugin:dev.mosael.comfyui");
    expect(named.textContent).not.toContain("ComfyUI · http://192.168.3.15:8188");
    expect(await hoverHint(named.querySelector("[data-engine-name]") as HTMLElement))
      .toContain("来自 krea2-text-2-image · ComfyUI · http://192.168.3.15:8188");
    //: 用的模型已经不在选项里(连接删了):问后端它叫什么、现在怎么了 —— 不写 `plugin:… · …#app`
    const gone = await footer("连接删了");
    await waitFor(() => expect(gone.querySelector("[data-engine-name]")?.textContent).toBe("之前选的模型 · genModelUnusable"));
    expect(gone.textContent).not.toContain("plugin:");
    expect(gone.textContent).not.toContain("#app");
  });
});

describe("出图按高度定尺寸,不铺满", () => {
  const done = (ids: string[]) => ({
    id: "g1",
    workspace_id: "w1",
    session_id: "s1",
    job_id: null,
    provider: "comfyui",
    model: "古风女孩1",
    kind: "image",
    request: { prompt: "跳舞的女孩" },
    result_asset_id: ids[0] ?? null,
    result_asset_ids: ids,
    error: null,
    created_at: "2026-10-05T00:00:00Z",
    updated_at: "2026-10-05T00:01:00Z",
    costs: [],
    cost_confidence: null,
  });

  it("多张:每张 220px 高、不伸展 —— 单数的最后一张不再被拉成整行宽(维护者:「太大了」)", async () => {
    renderStudio({ generations: [done(["a1", "a2", "a3"])] });
    //: 会话、选项、记录三份到齐才画得出来:机器忙时(整套并行跑)一秒不够,放宽等待
    const buttons = await screen.findAllByRole("button", { name: "imagePreviewTitle" }, { timeout: 5000 });
    expect(buttons).toHaveLength(3);
    for (const button of buttons) {
      expect(button.className).not.toMatch(/flex-\[1_1/);
      expect(button.querySelector("img")!.className.split(" ")).toEqual(expect.arrayContaining(["h-[220px]", "w-auto"]));
    }
  });

  //: 出视频的那一条:共用播放器(不是原生 controls),它的「全屏」开同一个灯箱,和本会话的其他产出一起翻。
  it("视频那一条的「全屏」开灯箱,画廊里有本会话的图和这段视频", async () => {
    const clip = { ...done(["v1"]), id: "g2", kind: "video", request: { prompt: "海浪" }, created_at: "2026-10-05T00:02:00Z" };
    renderStudio({ generations: [done(["a1", "a2"]), clip] });
    const player = await waitFor(() => {
      const found = document.querySelector('[data-generated-video="v1"]');
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    expect(player.querySelector("video[controls]"), "不是浏览器原生那条控件").toBeNull();
    fireEvent.click(within(player).getByRole("button", { name: "boardFullscreen" }));
    const lightbox = await waitFor(() => {
      const found = document.querySelector<HTMLElement>(".PhotoView-Portal");
      expect(found).not.toBeNull();
      return found!;
    });
    expect(lightbox.textContent).toContain("3 / 3");
    expect(lightbox.textContent).toContain("海浪");
    expect(lightbox.querySelector("video")).not.toBeNull();
  });

  it("一张:最高 360px,宽跟着比例走", async () => {
    renderStudio({ generations: [done(["a1"])] });
    const [button] = await screen.findAllByRole("button", { name: "imagePreviewTitle" });
    expect(button.querySelector("img")!.className.split(" ")).toEqual(expect.arrayContaining(["max-h-[360px]", "w-auto"]));
  });
});

describe("会话记着的模型用不了:显示的就是它,不拿默认模型顶上(ADR 0045 修订之一)", () => {
  //: 维护者撞到的:会话记着他的 ComfyUI 表单(那台还没升级),下拉、右栏、底下那枚按钮却全是默认的 gpt-image,点发送就拿它生成了
  const KREA = { ...session(true), provider_profile_id: "p9", model: "krea2-text-2-image.json#app", title: "用 krea2 的那段" };
  const OUTDATED = {
    provider_profile_id: "p9", model: "krea2-text-2-image.json#app", model_label: "krea2-text-2-image 的表单",
    profile_name: "ComfyUI · http://192.168.3.15:8188", group: { id: "krea2-text-2-image.json", label: "krea2-text-2-image", entry: "form", order: 1 },
    reason: "工作流「krea2-text-2-image」的表单还是旧格式 —— 到工作流库里点「查看并升级」", upgrade: true, plugin_instance_id: "inst9",
  };

  it("下拉、右栏、底下那枚按钮写的是记着的那个(标着需要升级),说原因和两条路;发送键灰着,按什么都发不出去", async () => {
    const { writes } = renderStudio({ sessions: [KREA], missing: OUTDATED });
    const panel = screen.getByRole("complementary", { name: "generationEngineSettings", hidden: true });
    const trigger = await waitFor(() => {
      const found = panel.querySelector<HTMLElement>("[data-engine-picker] button");
      expect(found?.textContent).toBe("krea2-text-2-image 的表单 · genModelNeedsUpgrade");
      return found!;
    });
    expect(trigger).toHaveAttribute("data-missing");
    const note = panel.querySelector<HTMLElement>("[data-model-missing]")!;
    expect(note.textContent).toContain("旧格式");
    expect(note.textContent).toContain("来自 krea2-text-2-image · ComfyUI · http://192.168.3.15:8188");
    expect(within(note).getByRole("button", { name: "genModelMissingUpgrade" })).toBeTruthy();
    expect(within(note).getByRole("button", { name: "genModelMissingPickAnother" })).toBeTruthy();
    expect(panel.textContent, "不摆默认模型的参数").not.toContain("genSectionOutput");
    expect(document.body.textContent, "哪儿都不写默认的那个").not.toContain("gpt-image-1");
    const chip = document.querySelector<HTMLElement>("[data-engine-chip]")!;
    expect(chip.textContent).toBe("krea2-text-2-image 的表单 · genModelNeedsUpgrade");

    const send = screen.getByRole("button", { name: "generate" });
    expect(send).toBeDisabled();
    const box = screen.getByRole("textbox", { name: "genPromptLabel" });
    fireEvent.change(box, { target: { value: "一只猫" } });
    fireEvent.keyDown(box, { key: "Enter", metaKey: true });
    fireEvent.click(send);
    expect(send).toBeDisabled();
    expect(writes.filter((one) => one.url.includes("/api/generation/jobs")), "点不出请求").toEqual([]);
  });

  it("自己在下拉里挑了别的才换成那个,照常记进会话、发得出去", async () => {
    const { writes } = renderStudio({ sessions: [KREA], missing: OUTDATED });
    const panel = screen.getByRole("complementary", { name: "generationEngineSettings", hidden: true });
    await waitFor(() => expect(panel.querySelector("[data-model-missing]")).not.toBeNull());
    fireEvent.click(within(panel.querySelector<HTMLElement>("[data-model-missing]")!).getByRole("button", { name: "genModelMissingPickAnother" }));
    fireEvent.click(await screen.findByRole("option", { name: /^gpt-image-1/ }));
    await waitFor(() => expect(panel.querySelector("[data-model-missing]")).toBeNull());
    expect(writes.find((one) => one.method === "PATCH")?.body).toMatchObject({ provider_profile_id: "p1", model: "gpt-image-1" });
    fireEvent.change(screen.getByRole("textbox", { name: "genPromptLabel" }), { target: { value: "一只猫" } });
    fireEvent.click(screen.getByRole("button", { name: "generate" }));
    await waitFor(() => expect(writes.some((one) => one.url.includes("/api/generation/jobs"))).toBe(true));
    expect(writes.find((one) => one.url.includes("/api/generation/jobs"))!.body).toMatchObject({ model: "gpt-image-1" });
  });
});

describe("没选过会话时停在「新的一条」;「+」不建空会话(UC-03、UC-10)", () => {
  it("有会话也不落进最近那一条:标题是「新生成」、没有那条的记录;第一次提交才建会话、记下用的模型", async () => {
    localStorage.removeItem("mosael.generation.session.w1.create");
    const record = { id: "g1", workspace_id: "w1", session_id: "s1", job_id: null, provider_profile_id: "p1", provider: "openai",
                     model: "gpt-image-1", kind: "image", request: { prompt: "画板那一次" }, result_asset_id: "a1",
                     result_asset_ids: ["a1"], error: null, created_at: "2026-10-06T00:00:00Z", updated_at: "2026-10-06T00:00:11Z" };
    const { writes } = renderStudio({ generations: [record] });
    expect(await screen.findByRole("button", { name: /同事的海报/ })).toBeTruthy();
    expect(screen.getAllByText("generationNewSession").length).toBeGreaterThan(0);
    expect(screen.queryByText("画板那一次"), "不是那条会话").toBeNull();
    fireEvent.change(screen.getByRole("textbox", { name: "genPromptLabel" }), { target: { value: "一只猫" } });
    fireEvent.click(screen.getByRole("button", { name: "generate" }));
    await waitFor(() => expect(writes.some((one) => one.url.includes("/api/generation/jobs"))).toBe(true));
    const created = writes.filter((one) => one.url.endsWith("/api/generation/sessions"));
    expect(created).toHaveLength(1);
    expect(created[0].body).toMatchObject({ kind: "image", provider_profile_id: "p1", model: "gpt-image-1" });
    expect(writes.find((one) => one.url.includes("/api/generation/jobs"))!.body).toMatchObject({ session_id: "s-new" });
  });

  it("「+」只换成新的一条,不在服务端建会话", async () => {
    const { writes } = renderStudio();
    const plus = await screen.findByRole("button", { name: "generationNewSession" });
    await waitFor(() => expect(screen.getAllByText("同事的海报"), "开着 s1:列表一行、标题一行").toHaveLength(2));
    fireEvent.click(plus);
    fireEvent.click(plus);
    expect(writes.filter((one) => one.url.endsWith("/api/generation/sessions"))).toEqual([]);
    expect(screen.getAllByText("同事的海报"), "标题换成了新的一条").toHaveLength(1);
  });
});

describe("生成框:⌘Enter / Ctrl+Enter 生成,回车换行(UC-04)", () => {
  it("回车不发;⌘Enter、Ctrl+Enter 发;输入框旁边说着快捷键", async () => {
    localStorage.removeItem("mosael.generation.session.w1.create");
    const { writes } = renderStudio();
    const box = await screen.findByRole("textbox", { name: "genPromptLabel" });
    fireEvent.change(box, { target: { value: "第一行" } });
    const settle = () => new Promise((resolve) => setTimeout(resolve, 50));
    fireEvent.keyDown(box, { key: "Enter" });
    await settle();
    expect(writes, "回车是换行:会话、生成都不建").toEqual([]);
    fireEvent.keyDown(box, { key: "Enter", isComposing: true, metaKey: true });
    await settle();
    expect(writes, "组词时的回车归输入法").toEqual([]);
    expect(document.querySelector("[data-submit-hint]")?.textContent).toContain("genSubmitHint");
    fireEvent.keyDown(box, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(writes.filter((one) => one.url.includes("/api/generation/jobs"))).toHaveLength(1));
  });
});
