/** @vitest-environment jsdom */
import React from "react";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

/**
 * Markdown 正文里的图(回复里贴的图、文档解析出来的插图)点开看大图,左右翻的是这一段里的全部图。
 * 不接管 Streamdown 自己的图片组件 —— 只接住点在图上的那一下,别处(图上的下载钮、链接)照旧。
 */

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { IMAGE_PREVIEW_EVENT, type ImagePreviewRequest } from "@/components/app/image-preview-request";
import { AgentMarkdown } from "./Markdown";

const requests: ImagePreviewRequest[] = [];
const onRequest = (event: Event) => requests.push((event as CustomEvent<ImagePreviewRequest>).detail);

afterEach(() => {
  cleanup();
  requests.length = 0;
  document.removeEventListener(IMAGE_PREVIEW_EVENT, onRequest);
});

it("点第二张图:请求带着这一段的两张,从第二张开始", async () => {
  document.addEventListener(IMAGE_PREVIEW_EVENT, onRequest);
  const view = render(<AgentMarkdown>{"一张图:\n\n![流程图](https://x.test/a.png)\n\n又一张:\n\n![](https://x.test/b.png)"}</AgentMarkdown>);
  await waitFor(() => expect(view.container.querySelectorAll('img[data-streamdown="image"]')).toHaveLength(2));
  fireEvent.click(view.container.querySelectorAll('img[data-streamdown="image"]')[1]);
  expect(requests).toEqual([
    {
      src: "https://x.test/b.png",
      title: undefined,
      gallery: [
        { src: "https://x.test/a.png", title: "流程图" },
        { src: "https://x.test/b.png", title: undefined },
      ],
    },
  ]);
});

it("点在图以外的地方不开", async () => {
  document.addEventListener(IMAGE_PREVIEW_EVENT, onRequest);
  const view = render(<AgentMarkdown>{"一段字\n\n![图](https://x.test/a.png)"}</AgentMarkdown>);
  await waitFor(() => expect(view.container.querySelector("p")).not.toBeNull());
  fireEvent.click(view.container.querySelector("p")!);
  expect(requests).toEqual([]);
});
