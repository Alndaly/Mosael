import { describe, expect, it } from "vitest";

import { releaseStaleModalSideEffects, type ModalTeardownTarget } from "./modalTeardownGuard";

/**
 * 最小 document 替身:仓库里没装 jsdom(其余 21 个测试文件都是纯逻辑),所以用注入的替身来测
 * 这段清理的**分支与作用范围** —— 「有模态层开着就不动」和「只碰该碰的属性」正是会回归的部分。
 */
function fakeDocument(opts: { hasOpenModal?: boolean; style?: Record<string, string> }): {
  target: ModalTeardownTarget;
  style: Record<string, string>;
  removedAttrs: string[];
  seenSelectors: string[];
} {
  const style: Record<string, string> = { ...(opts.style ?? {}) };
  const removedAttrs: string[] = [];
  const seenSelectors: string[] = [];
  return {
    style,
    removedAttrs,
    seenSelectors,
    target: {
      querySelector(selector) {
        seenSelectors.push(selector);
        return opts.hasOpenModal ? {} : null;
      },
      body: {
        style: {
          getPropertyValue: (name: string) => style[name] ?? "",
          removeProperty: (name: string) => {
            const previous = style[name] ?? "";
            delete style[name];
            return previous;
          },
        } as ModalTeardownTarget["body"]["style"],
        removeAttribute: (name: string) => removedAttrs.push(name),
      },
    },
  };
}

const LEAKED = { "pointer-events": "none", overflow: "hidden" };

describe("releaseStaleModalSideEffects", () => {
  it("已无模态层时,抹掉卡住的 pointer-events 与滚动锁", () => {
    const doc = fakeDocument({ style: LEAKED });
    releaseStaleModalSideEffects(doc.target);
    expect(doc.style["pointer-events"]).toBeUndefined();
    expect(doc.style.overflow).toBeUndefined();
    expect(doc.removedAttrs).toContain("data-scroll-locked");
  });

  it("还有模态层开着时一律不动 —— 那些副作用此刻是正当的", () => {
    const doc = fakeDocument({ hasOpenModal: true, style: LEAKED });
    releaseStaleModalSideEffects(doc.target);
    expect(doc.style["pointer-events"]).toBe("none");
    expect(doc.style.overflow).toBe("hidden");
    expect(doc.removedAttrs).toEqual([]);
  });

  it("只清模态相关的属性,不碰 body 上别人写的样式", () => {
    const doc = fakeDocument({ style: { ...LEAKED, background: "red" } });
    releaseStaleModalSideEffects(doc.target);
    expect(doc.style.background).toBe("red");
    expect(doc.style.overflow).toBeUndefined();
  });

  it("本来干净时是无操作(幂等,可重复调用)", () => {
    const doc = fakeDocument({});
    releaseStaleModalSideEffects(doc.target);
    releaseStaleModalSideEffects(doc.target);
    expect(doc.style).toEqual({});
  });

  it("「开着的模态层」只认 data-state=open,且覆盖四种浮层角色", () => {
    const doc = fakeDocument({});
    releaseStaleModalSideEffects(doc.target);
    const selector = doc.seenSelectors[0];
    expect(selector).toContain('[data-state="open"]');
    for (const role of ["dialog", "alertdialog", "menu", "listbox"]) {
      expect(selector).toContain(`[role="${role}"]`);
    }
  });
});
