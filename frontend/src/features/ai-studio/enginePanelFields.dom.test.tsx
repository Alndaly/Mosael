/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { CONTROL_HEIGHT, CONTROL_SQUARE } from "@/components/ui/control-size";

/**
 * 创作页右栏「引擎参数」里的字段**都是同一档**:md(40px 高、text-ui-sm、rounded-md),和「音色」那一格一样。
 *
 * 维护者:「引擎参数这里的输入框风格不一致,音色这个输入框的高度是正确的」。此前模型、尺寸、张数、调参经
 * `PARAMETER_CONTROL_CLASS` 写死成 32px 的大圆角,音色、语速走字段默认档 40px —— 同一栏里两种框。那个常量是当变量传进去的,
 * `design/fieldScale.test.ts`(只看字面量)看不见它,所以这条在**渲染出来的右栏**上查,五种会话各一遍。
 *
 * 照 components/ui/fieldSize.dom.test.tsx 的写法,按「东西在哪」查:高度类必须挂在真正画出边框的那个元素上(input 本身、
 * role=combobox 的触发器、SearchableSelect 那颗带 bg-field 的按钮),而且恰好一个 —— 两个同时在就是 cn() 没合并掉。
 * 每种会话还钉一个下限个数:右栏一格都没渲染出来时「每一格都是 md」天然成立,那不算过。
 * 挨着字段的方钮(试听)是和 md 字段同高的 icon(40px)。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { AiStudio } from "@/features/ai-studio/AiStudio";
import { ImagePreviewProvider } from "@/components/app/image-preview";

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
      matches: false, media: query, onchange: null, addEventListener: () => {}, removeEventListener: () => {},
      addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
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
  localStorage.setItem("mosael:tab:ai-studio-create-filter", "all");
});

const option = (kind: string, model: string, capabilities: Record<string, unknown>) => ({
  id: `p1:${kind}:${model}`, provider_profile_id: "p1", plugin_instance_id: "", profile_name: "演示", provider: "alibaba", kind,
  model, model_label: model, group: null, capabilities, capabilities_known: true, adapter_available: true, is_default: true,
});

/** 每一种都把右栏能出的控件尽量摆全:下拉、可手填的尺寸、数字框、文字框、插件自己声明的整数和枚举、开关、宿主的枚举。 */
const OPTIONS = [
  option("image", "img-model", {
    modes: ["text-to-image"],
    parameter_keys: ["size", "num_images", "seed", "negative_prompt", "prompt_extend", "quality", "steps", "sampler"],
    sizes: ["1024x1024", "1024x576"], default_size: "1024x1024", custom_size: { minimum: 256 }, max_num_images: 4,
    boolean_parameters: ["prompt_extend"], parameter_choices: { quality: ["low", "high"] },
    parameter_schema: {
      steps: { type: "integer", minimum: 1, maximum: 50, default: 20, title: "Steps" },
      sampler: { type: "string", enum: ["euler", "dpm"], default: "euler", title: "Sampler" },
    },
  }),
  option("video", "video-model", {
    modes: ["text-to-video"],
    parameter_keys: ["duration_seconds", "resolution", "aspect_ratio", "generate_audio", "seed"],
    duration_seconds: [5, 10], default_duration_seconds: 5, resolutions: ["720P", "1080P"], default_resolution: "1080P",
    aspect_ratios: ["16:9", "9:16"], default_aspect_ratio: "16:9",
  }),
  option("audio", "music-model", {
    modes: ["text-to-music"],
    parameter_keys: ["lyrics", "instrumental", "vocal_gender", "output_format", "duration_seconds"],
    boolean_parameters: ["instrumental"], max_lyrics_chars: 2000, min_duration_seconds: 10, max_duration_seconds: 240,
    parameter_schema: { vocal_gender: { type: "string", enum: ["female", "male"], title: "Vocal gender" } },
    parameter_choices: { output_format: ["mp3", "wav"] },
  }),
];
const ENGINES = [
  { id: "builtin:edge", label: "Edge 语音", needs_key: false, needs_voice_id: false,
    voices: ["zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"], supports_speed: true, note: "免费", ready: true, clones_voices: false },
  { id: "builtin:volcano-podcast", label: "火山播客", needs_key: true, needs_voice_id: false,
    voices: ["voice-a", "voice-b"], supports_speed: true, note: "", ready: true, clones_voices: false },
];
const EDGE_VOICES = [
  { value: "zh-CN-XiaoxiaoNeural", label: "晓晓(女·温暖)" },
  { value: "zh-CN-YunxiNeural", label: "云希(男·阳光)" },
];
const PODCAST_VOICES = [{ value: "voice-a", label: "大壹先生" }, { value: "voice-b", label: "咪仔同学" }];

const SESSIONS: Record<string, { kind: string; provider_profile_id: string | null; model: string }> = {
  image: { kind: "image", provider_profile_id: "p1", model: "img-model" },
  video: { kind: "video", provider_profile_id: "p1", model: "video-model" },
  music: { kind: "audio", provider_profile_id: "p1", model: "music-model" },
  speech: { kind: "speech", provider_profile_id: null, model: "builtin:edge" },
  podcast: { kind: "podcast", provider_profile_id: null, model: "builtin:volcano-podcast" },
};

function renderMode(mode: keyof typeof SESSIONS) {
  const session = { id: "s1", workspace_id: "w1", title: mode, ...SESSIONS[mode], is_mine: true, shared: false,
                    created_at: "2026-10-08T00:00:00Z", updated_at: "2026-10-08T00:00:00Z" };
  localStorage.setItem("mosael.generation.session.w1.create", "s1");
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    if (url.includes("/api/generation/options")) {
      const kind = new URL(url, "http://x").searchParams.get("kind");
      return json(kind ? OPTIONS.filter((one) => one.kind === kind) : OPTIONS);
    }
    if (url.includes("/api/generation/sessions")) return json([session]);
    if (url.includes("/api/tts/engines")) return json(ENGINES);
    if (url.includes("/api/tts/voices")) return json(url.includes("volcano-podcast") ? PODCAST_VOICES : EDGE_VOICES);
    if (url.includes("/api/tts/config")) return json({ engine: "f5-tts" });
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
}

const HEIGHTS = Object.values(CONTROL_HEIGHT);

/** 右栏里画出边框的那些单行字段:输入框、role=combobox 的触发器、SearchableSelect 那颗按钮(它是 button,不是 combobox)。 */
function fieldsIn(panel: HTMLElement): HTMLElement[] {
  const found = panel.querySelectorAll<HTMLElement>(
    "input:not([type=hidden]):not([type=checkbox]):not([type=file]), [role=combobox], button.bg-field",
  );
  return [...new Set(found)];
}

const describeField = (element: HTMLElement) =>
  `${element.tagName.toLowerCase()} ${element.getAttribute("aria-label") ?? element.textContent?.trim() ?? ""}`;

describe("创作页右栏:字段都是「音色」那一档(md)", () => {
  it.each([
    //: 下限:模型、可手填的尺寸、张数、种子、反向提示词、扩写开关、Steps、Sampler、quality
    ["image", 9],
    //: 模型、分辨率、比例、时长、带不带声、种子
    ["video", 6],
    //: 模型、人声、时长、人声性别、格式(歌词是多行文字框,不在这一档里比)
    ["music", 5],
    //: 模型、音色、语速
    ["speech", 3],
    //: 模型、发音人 A、发音人 B、语速
    ["podcast", 4],
  ] as const)("%s", async (mode, atLeast) => {
    renderMode(mode);
    const panel = await screen.findByRole("complementary", { name: "generationEngineSettings" });
    const fields = await waitFor(() => {
      const now = fieldsIn(panel);
      expect(now.length).toBeGreaterThanOrEqual(atLeast);
      return now;
    });
    const off = fields
      .map((field) => {
        const classes = field.className.split(/\s+/);
        const heights = classes.filter((name) => HEIGHTS.includes(name as (typeof HEIGHTS)[number]));
        const wrong =
          heights.length !== 1 || heights[0] !== CONTROL_HEIGHT.md
            || !classes.includes("text-ui-sm") || !classes.includes("rounded-md")
            || classes.some((name) => ["rounded-lg", "px-2.5", "font-medium", "border-border"].includes(name));
        return wrong ? `${describeField(field)}: ${field.className}` : null;
      })
      .filter(Boolean);
    expect(off, "右栏里每一格都该是 md 档(h-10 / text-ui-sm / rounded-md),和音色那一格一样").toEqual([]);
  });

  it.each([
    ["speech", 1],
    ["podcast", 2],
  ] as const)("%s:试听键贴在下拉右边,是和 md 字段同高的方钮", async (mode, count) => {
    renderMode(mode);
    const panel = await screen.findByRole("complementary", { name: "generationEngineSettings" });
    const previews = await waitFor(() => {
      const found = within(panel).getAllByRole("button", { name: "voicePreview" });
      expect(found).toHaveLength(count);
      return found;
    });
    for (const preview of previews) {
      expect(preview.className.split(/\s+/)).toContain(CONTROL_SQUARE.md);
      //: 和下拉在同一行:同一个父元素里就是那颗下拉
      const row = preview.parentElement!;
      expect(row.querySelector("[role=combobox]")).toBeTruthy();
    }
  });

  it("speech:音色、语速的标签和模型那一栏同一档字号(右栏的标签不是一大一小)", async () => {
    renderMode("speech");
    const panel = await screen.findByRole("complementary", { name: "generationEngineSettings" });
    const model = (await within(panel).findByText("wfModelPreset")).closest("label")!;
    expect(model.className.split(/\s+/)).toContain("text-ui-sm");
    for (const label of ["voiceEngineVoice", "voiceSpeed"]) {
      const span = await within(panel).findByText(label);
      expect(span.className.split(/\s+/), label).toContain("text-ui-sm");
      expect(span.className.split(/\s+/), label).not.toContain("text-ui-xs");
    }
  });
});
