/**
 * 文案表按语言分块、按需取:取过的直接给,还没取到的那一种退到已经取到的那一种,一种都没有就直说。
 */
import { describe, expect, it } from "vitest";

import { messages } from "@/app/messages";
import { loadMessages, messagesFor, messagesLoaded } from "@/app/messageTables";

describe("运行时的文案表", () => {
  it("取到的就是那种语言的整张表", async () => {
    expect(await loadMessages("en-US")).toEqual(messages["en-US"]);
    expect(await loadMessages("zh-CN")).toEqual(messages["zh-CN"]);
    expect(messagesLoaded("en-US") && messagesLoaded("zh-CN")).toBe(true);
    expect(messagesFor("en-US").retry).toBe(messages["en-US"].retry);
  });

  it("同一种语言只取一次", async () => {
    const [a, b] = await Promise.all([loadMessages("zh-CN"), loadMessages("zh-CN")]);
    expect(a).toBe(b);
  });
});
