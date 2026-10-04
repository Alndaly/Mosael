/** @vitest-environment jsdom */
/**
 * 花字描边在 DOM 上的样子:预览不用 canvas 画字,是 Monitor 把 `textStyleCss` 的结果交给 React
 * 写成行内样式。所以「先画描边、再画填充」能不能生效,看的是**元素上真的有没有那条声明** ——
 * 属性名写错一个字母,React 照样渲染、浏览器静默丢掉,描边又回到盖在字上面,而只看返回对象的
 * 单测是绿的。
 *
 * 另一半是检查器:描边按字号封顶之后,滑杆的上限要跟着字号走,存储值超出时要说明「按上限画」。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DEFAULT_TEXT_STYLE, textStyleCss } from "@/features/editor/textStyle";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  listLuts: vi.fn(async () => []),
}));
vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});

import { Inspector } from "./Inspector";
import { hoverHint } from "@/test/hint";

const IDENTITY = { scale: 1, x: 0, y: 0, rotation: 0, opacity: 1 };

describe("预览里的花字描边", () => {
  it("元素上有 paint-order: stroke fill,线宽是外圈的两倍(随画幅缩放的 cqw)", () => {
    const style = { ...DEFAULT_TEXT_STYLE, font_size: 96, stroke_width: 8, stroke_color: "#112233" };
    render(<div data-testid="title" style={textStyleCss(style, IDENTITY, 1920)}>花字</div>);
    const el = screen.getByTestId("title");
    expect(el.style.getPropertyValue("paint-order")).toBe("stroke fill");
    // 外圈 4px(存储线宽 8 的一半)→ 线宽 8px → 8/1920 个画幅宽
    expect(el.style.getPropertyValue("-webkit-text-stroke-width")).toBe(`${(8 / 1920) * 100}cqw`);
    expect(el.style.getPropertyValue("-webkit-text-stroke-color")).toBe("rgb(17, 34, 51)");
  });

  it("超过字号上限时按上限画:字号 12、存储线宽 6 → 外圈 1.8px、线宽 3.6px", () => {
    const style = { ...DEFAULT_TEXT_STYLE, font_size: 12, stroke_width: 6 };
    render(<div data-testid="small" style={textStyleCss(style, IDENTITY, 1920)}>花字</div>);
    const width = screen.getByTestId("small").style.getPropertyValue("-webkit-text-stroke-width");
    expect((parseFloat(width) / 100) * 1920).toBeCloseTo(3.6, 6);
  });

  it("没有描边就不留任何描边声明", () => {
    render(<div data-testid="plain" style={textStyleCss(DEFAULT_TEXT_STYLE, IDENTITY, 1920)}>花字</div>);
    const el = screen.getByTestId("plain");
    expect(el.style.getPropertyValue("paint-order")).toBe("");
    expect(el.style.getPropertyValue("-webkit-text-stroke-width")).toBe("");
  });
});

function renderTitleInspector(textStyle: Record<string, unknown>) {
  const clip = {
    id: "t1", asset_id: null, asset_kind: "", timeline_start: 0, src_in: 0, src_out: 3, speed: 1, gain: 1,
    muted: false, text_override: "花字", effects: { text_style: textStyle }, transform: {},
  } as never;
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Inspector
        workspaceId="w1"
        selectedClip={clip}
        assets={[]}
        isTitleText
        onDeleteClip={vi.fn()}
        onSetEffects={vi.fn()}
        onSetTransform={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

/** 描边那一行的滑杆:标签 span 带悬停说明,滑杆在它右边。 */
function strokeSlider(): HTMLElement {
  const label = screen.getByText("textStroke");
  const slider = label.parentElement?.querySelector<HTMLElement>("[role=slider]");
  if (!slider) throw new Error("描边那一行没有滑杆");
  return slider;
}

describe("检查器的描边滑杆", () => {
  it("上限跟着字号走:默认字号 48 时最大 14(外圈封顶 7.2px)", () => {
    renderTitleInspector({ font_size: 48, stroke_width: 6 });
    expect(strokeSlider().getAttribute("aria-valuemax")).toBe("14");
    expect(strokeSlider().getAttribute("aria-valuenow")).toBe("6");
    expect(screen.queryByText("textStrokeCapped")).toBeNull();
  });

  it("描边的标签悬停说明描边画在哪、最粗多少", async () => {
    renderTitleInspector({ font_size: 48, stroke_width: 6 });
    const label = screen.getByText("textStroke");
    expect(await hoverHint(label)).toBe("textStrokeHint");
  });

  it("存储值超过这个字号的上限:滑杆停在上限,并说明按上限绘制(存储值不动)", () => {
    renderTitleInspector({ font_size: 12, stroke_width: 6 });
    expect(strokeSlider().getAttribute("aria-valuemax")).toBe("3");
    expect(strokeSlider().getAttribute("aria-valuenow")).toBe("3");
    expect(screen.getByText("textStrokeCapped")).toBeTruthy();
  });
});
