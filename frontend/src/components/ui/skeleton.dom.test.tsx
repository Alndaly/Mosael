/** @vitest-environment jsdom */
import React from "react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { Skeleton } from "./skeleton";

afterEach(cleanup);

//: 样子(底色、扫光、减少动态)全在 design/tokens.css 的 .skeleton 里 —— 组件只负责挂上它。
//: jsdom 不跑动画,编出来的规则在 design/compiledCascade.test.ts 里核对。
it("默认挂上设计系统的扫光占位,尺寸和圆角交给调用处", () => {
  const { container } = render(<Skeleton className="h-4 w-24 rounded-lg" />);
  const block = container.firstElementChild as HTMLElement;
  expect(block.dataset.slot).toBe("skeleton");
  expect(block).toHaveClass("skeleton", "h-4", "w-24", "rounded-lg");
  //: 调用处的圆角换掉默认的,不是两条圆角类叠着。
  expect(block).not.toHaveClass("rounded-md");
  expect(block.className).not.toMatch(/\banimate-/);
});
