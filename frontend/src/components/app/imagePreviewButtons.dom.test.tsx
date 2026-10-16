/** @vitest-environment jsdom */
import * as React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

/**
 * 灯箱右上角那两颗(关闭 / 保存到本地)是**同一颗基础件**画的。
 *
 * 维护者报的:「保存到本地」和「关闭」风格不一致 —— 位置、形状、底色、大小都对不上。保存那颗当时为了不涨
 * `design/controlOverrides` 的存量,用 `variant="secondary" size="icon-sm"`(跟主题走的实心方角钮),
 * 而关闭那颗是手写在调用处的一长串 className(浮在暗底上的半透明圆钮):两颗并排放在同一处,没有一样一样。
 * 做法是把那套外观收进 `components/ui/floating-button`(见那里的说明),灯箱这两颗都用它。
 *
 * 所以这里**不比两根字符串**,而是照着基础件导出的那几样逐一对:外观(外壳、底色、悬停、焦点圈、图标大小)
 * 必须一模一样,位置必须是同一层、同一顶边,并且正好隔着一颗钮的距离(8px 栅格)。
 */

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/lib/download", () => ({ saveAssetToDisk: vi.fn() }));

import { ImagePreviewProvider, useImagePreview } from "@/components/app/image-preview";
import type { ImagePreviewItem } from "@/components/app/imagePreviewContext";
import { FLOATING_BUTTON, FLOATING_GAP, FLOATING_SIZE, FLOATING_TOP_RIGHT } from "@/components/ui/floating-button";

const items: ImagePreviewItem[] = [{ src: "/preview/img-1", title: "一张图.png", assetId: "img-1" }];

function Opener() {
  const { openImagePreview } = useImagePreview();
  return (
    <button type="button" onClick={() => openImagePreview({ ...items[0], gallery: items })}>看大图</button>
  );
}

async function open() {
  render(
    <ImagePreviewProvider>
      <Opener />
    </ImagePreviewProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "看大图" }));
  await waitFor(() => expect(document.querySelector(".PhotoView-Portal")).not.toBeNull());
}

const closeButton = () => document.querySelector<HTMLElement>("[data-image-preview-close]")!;
const saveButton = () => document.querySelector<HTMLElement>("[data-image-preview-save]")!;

/** 类名里带某个前缀的那几个(`top-*`、`z-*`)—— 比两颗钮是不是同一顶边、同一层,不比整串。 */
const prefixed = (element: HTMLElement, prefix: string) => [...element.classList].filter((one) => one.startsWith(prefix)).sort();

/** 离右边缘多少 px:`right-2`(刻度 4 → 8)和 `right-[52px]` 都读得出来。 */
function rightOffset(element: HTMLElement): number {
  const token = [...element.classList].find((one) => /^right-(\d+|\[\d+px\])$/.test(one));
  if (!token) throw new Error(`这颗钮没有 right-* 定位:${element.className}`);
  const exact = /\[(\d+)px\]/.exec(token);
  return exact ? Number(exact[1]) : Number(/right-(\d+)/.exec(token)![1]) * 4;
}

afterEach(cleanup);

it("关闭与「保存到本地」是同一颗基础件画的:外观逐样相同", async () => {
  await open();
  const skin = FLOATING_BUTTON.split(/\s+/).filter(Boolean);
  //: 外观要是空串,下面逐个 contains 天然全过 —— 先钉住「它确实是一串」。
  expect(skin.length).toBeGreaterThan(8);
  for (const token of skin) {
    expect(closeButton().classList.contains(token), `关闭键少了 ${token}`).toBe(true);
    expect(saveButton().classList.contains(token), `保存到本地少了 ${token}`).toBe(true);
  }
});

it("位置一致:同一层、同一顶边,保存到本地在关闭键左边、正好隔一颗钮的距离", async () => {
  await open();
  expect([...closeButton().classList], "两颗都是浮在画面上的那一层").toContain("fixed");
  expect([...saveButton().classList]).toContain("fixed");
  expect(prefixed(closeButton(), "top-")).toEqual(prefixed(saveButton(), "top-"));
  expect(prefixed(closeButton(), "z-")).toEqual(prefixed(saveButton(), "z-"));
  expect(rightOffset(saveButton()) - rightOffset(closeButton())).toBe(FLOATING_SIZE + FLOATING_GAP);
  //: 各自的位子来自基础件那张表 —— 调用方没有自己算 `right-[…]`(算了就又会分成两份)。
  for (const token of FLOATING_TOP_RIGHT[0].split(" ")) expect(closeButton().classList.contains(token)).toBe(true);
  for (const token of FLOATING_TOP_RIGHT[1].split(" ")) expect(saveButton().classList.contains(token)).toBe(true);
  //: 保存那颗不再住在库的顶栏里 —— 那一条点一下画面(视频的播放 / 暂停也算)就淡出去,
  //: 而关闭键一直都在,两颗并排却一颗在一颗不在,又是一种对不上。
  expect(saveButton().closest(".PhotoView-Slider__BannerWrap")).toBeNull();
});
