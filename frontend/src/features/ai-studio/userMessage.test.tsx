import { describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({
  assetFileUrl: (id: string) => `/file/${id}`,
  assetPreviewUrl: (id: string) => `/preview/${id}`,
}));

import { chatMediaGallery } from "./userMessage";

describe("聊天媒体画廊", () => {
  it("按消息顺序收齐图片和视频,排除音频并对重复素材去重", () => {
    const messages = [
      {
        role: "user",
        content:
          "看看这些\n[附件 asset_id=a 名称=第一张.HEIC 类型=image]\n[附件 asset_id=v 名称=片段.mp4 类型=video]",
      },
      { role: "assistant", content: "[附件 asset_id=fake 名称=别解析我.png 类型=image]" },
      {
        role: "user",
        content:
          "再看\n[附件 asset_id=b 名称=第二张.png 类型=image]\n[附件 asset_id=a 名称=第一张.HEIC 类型=image]\n[附件 asset_id=s 名称=声音.wav 类型=audio]",
      },
    ];

    expect(chatMediaGallery(messages)).toEqual([
      { src: "/preview/a", title: "第一张.HEIC" },
      { src: "/file/v", title: "片段.mp4", video: true },
      { src: "/preview/b", title: "第二张.png" },
    ]);
  });
});
