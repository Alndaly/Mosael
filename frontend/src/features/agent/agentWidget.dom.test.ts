/** @vitest-environment jsdom */
/**
 * 智能体小界面的安全边界(见 agentWidget.ts 文件头的四道墙)。每一条断言对应一道墙被拆掉时的具体后果:
 * - sandbox 多了 allow-same-origin → 框里的脚本和这一页同源,能读 localStorage、碰 DOM;
 * - CSP 不在 head 最前面 → 模型的内容先跑、或者 meta 落进 body 不生效,框里能随便联网;
 * - 高度消息不看来源 → 任何别的框(或者框里再塞的东西)都能把对话撑高缩矮。
 */
import { describe, expect, it } from "vitest";

import {
  HEIGHT_MESSAGE,
  WIDGET_CSP,
  WIDGET_MAX_HEIGHT,
  WIDGET_MIN_HEIGHT,
  WIDGET_SANDBOX,
  buildWidgetDocument,
  widgetHeightFrom,
} from "@/features/agent/agentWidget";

const theme = { scheme: "light" as const, vars: { "--foreground": "oklch(0.2 0 0)", "--card": "#fff" } };

function directives(csp: string): Map<string, string[]> {
  return new Map(
    csp.split(";").map((part) => {
      const [name, ...values] = part.trim().split(/\s+/);
      return [name, values] as const;
    }),
  );
}

describe("沙箱只给跑脚本这一项", () => {
  it("没有同源、导航、弹窗、表单、弹框", () => {
    expect(WIDGET_SANDBOX.split(/\s+/)).toEqual(["allow-scripts"]);
    expect(WIDGET_SANDBOX).not.toMatch(/same-origin|top-navigation|popups|forms|modals/);
  });
});

describe("CSP 断网、只放几个 CDN", () => {
  const csp = directives(WIDGET_CSP);

  it("默认什么都不许,fetch / XHR / WebSocket 全断", () => {
    expect(csp.get("default-src")).toEqual(["'none'"]);
    expect(csp.get("connect-src")).toEqual(["'none'"]);
  });

  it("不许再开框、开 worker、提交表单、改 base、塞插件", () => {
    for (const name of ["frame-src", "worker-src", "form-action", "base-uri", "object-src"]) {
      expect(csp.get(name), name).toEqual(["'none'"]);
    }
  });

  it("脚本来源只有内联和固定几家 CDN —— 没有任意 https、没有 eval", () => {
    const scripts = csp.get("script-src") ?? [];
    expect(scripts).not.toContain("https:");
    expect(scripts).not.toContain("*");
    expect(scripts).not.toContain("'unsafe-eval'");
    expect(scripts).toEqual(["'unsafe-inline'", "https://cdn.jsdelivr.net", "https://unpkg.com", "https://cdnjs.cloudflare.com"]);
  });
});

describe("拼出来的文档:我们的 head 在前,模型的 HTML 在 body", () => {
  it("CSP 是 head 里的第一个元素,早于引导脚本和模型的任何内容", () => {
    const html = '<script>window.x = 1</script><meta http-equiv="Content-Security-Policy" content="default-src *">';
    const doc = new DOMParser().parseFromString(buildWidgetDocument(html, theme), "text/html");
    const first = doc.head.firstElementChild;
    expect(first?.tagName).toBe("META");
    expect(first?.getAttribute("http-equiv")).toBe("Content-Security-Policy");
    expect(first?.getAttribute("content")).toBe(WIDGET_CSP);
    //: 模型写的那条放宽的 CSP 落在 body 里 —— meta CSP 只在 head 生效,它不算数。
    expect(doc.head.querySelectorAll('meta[http-equiv="Content-Security-Policy"]')).toHaveLength(1);
    expect(doc.body.querySelector('meta[http-equiv="Content-Security-Policy"]')).not.toBeNull();
    expect(doc.body.querySelector("script")?.textContent).toBe("window.x = 1");
  });

  it("模型给一整份文档也一样:它的 head 进不了我们的 head", () => {
    const html = '<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src *"><script src="https://evil.example/a.js"></script></head><body><p>hi</p></body></html>';
    const doc = new DOMParser().parseFromString(buildWidgetDocument(html, theme), "text/html");
    expect(doc.head.querySelectorAll('meta[http-equiv="Content-Security-Policy"]')).toHaveLength(1);
    expect(doc.head.firstElementChild?.getAttribute("content")).toBe(WIDGET_CSP);
    expect(doc.head.querySelector('script[src]')).toBeNull();
  });

  it("主题值只放颜色该有的字符:闭合 style 的值被丢掉", () => {
    const doc = buildWidgetDocument("<p>hi</p>", {
      scheme: "dark",
      vars: { "--card": "#111", "--primary": "red;}</style><script>alert(1)</script>" },
    });
    expect(doc).toContain("--card:#111;");
    expect(doc).toContain("color-scheme:dark");
    expect(doc).not.toContain("alert(1)");
  });
});

describe("高度消息只认这个框自己", () => {
  const frame = {} as Window;

  it("这个框报的:夹在上下限之间", () => {
    expect(widgetHeightFrom({ source: frame, data: { type: HEIGHT_MESSAGE, height: 320.4 } }, frame)).toBe(320);
    expect(widgetHeightFrom({ source: frame, data: { type: HEIGHT_MESSAGE, height: 99999 } }, frame)).toBe(WIDGET_MAX_HEIGHT);
    expect(widgetHeightFrom({ source: frame, data: { type: HEIGHT_MESSAGE, height: 0 } }, frame)).toBe(WIDGET_MIN_HEIGHT);
  });

  it("别的窗口发的、类型不对的、高度不是数的:一律不看", () => {
    expect(widgetHeightFrom({ source: {} as Window, data: { type: HEIGHT_MESSAGE, height: 300 } }, frame)).toBeNull();
    expect(widgetHeightFrom({ source: frame, data: { type: "other", height: 300 } }, frame)).toBeNull();
    expect(widgetHeightFrom({ source: frame, data: { type: HEIGHT_MESSAGE, height: "300" } }, frame)).toBeNull();
    expect(widgetHeightFrom({ source: frame, data: { type: HEIGHT_MESSAGE, height: Number.NaN } }, frame)).toBeNull();
    expect(widgetHeightFrom({ source: frame, data: null }, frame)).toBeNull();
  });

  it("框还没挂上(contentWindow 是 null)时不认任何消息", () => {
    expect(widgetHeightFrom({ source: null, data: { type: HEIGHT_MESSAGE, height: 300 } }, null)).toBeNull();
  });
});
