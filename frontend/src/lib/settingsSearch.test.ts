/**
 * 设置按「我要改什么」搜得到(体检 UM-15)。用真文案表,照用户实际输入的那些词搜:此前除了「成员」全是「没有找到」。
 */
import { describe, expect, it } from "vitest";

import { messages, type MessageKey } from "@/app/messages";
import { ADMIN_SETTINGS, SETTINGS_SEARCH, matchSettings } from "./settingsSearch";

type Translate = (key: MessageKey) => string;
const zh: Translate = (key) => messages["zh-CN"][key];
const en: Translate = (key) => messages["en-US"][key];
const sections = (query: string, t: Translate = zh) => matchSettings(SETTINGS_SEARCH, query, t).map(({ entry, hit }) => [entry.id, hit]);
const admin = (query: string, t: Translate = zh) => matchSettings(ADMIN_SETTINGS, query, t).map(({ entry }) => [entry.id, entry.tab]);

describe("设置搜索", () => {
  it("分区里那一行的名字搜得到,并说出是哪一行", () => {
    expect(sections("语言")).toEqual([["appearance", "settingsLanguage"]]);
    expect(sections("主题")).toEqual([["appearance", "settingsTheme"]]);
    expect(sections("密码")).toEqual([["account", "settingsPassword"]]);
    expect(sections("默认模型").map(([id]) => id)).toEqual(["provider-chat", "provider-image", "provider-video", "provider-audio"]);
  });

  it("只为搜索写的说法也对得上,但不当成「哪一行」显示", () => {
    expect(sections("kimi")).toContainEqual(["provider-chat", null]);
    expect(sections("深色")).toEqual([["appearance", null]]);
  });

  it("只在管理页的设置搜得到,指到哪个 tab", () => {
    expect(admin("代理")).toEqual([["proxy", "deployment"]]);
    expect(admin("镜像")).toEqual([["install-source", "engines"], ["model-source", "engines"]]);
    expect(admin("HuggingFace")).toEqual([["model-source", "engines"]]);
    expect(admin("邀请码")).toEqual([["invites", "members"]]);
    expect(admin("pip")).toEqual([["install-source", "engines"]]);
  });

  it("英文界面同样搜得到", () => {
    expect(sections("password", en)).toEqual([["account", "settingsPassword"]]);
    expect(sections("language", en)).toEqual([["appearance", "settingsLanguage"]]);
    expect(admin("proxy", en)).toEqual([["proxy", "deployment"]]);
  });

  it("空串列出全部分区,不列管理页的", () => {
    expect(sections("")).toHaveLength(SETTINGS_SEARCH.length);
  });
});
