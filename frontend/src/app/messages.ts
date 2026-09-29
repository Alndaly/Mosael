// 界面文案表的入口。正文按分区放在 messages/<语言>/<分区>.ts,两种语言的分区文件一一对应、键集相同
// (messages.test.ts 守着)。加 key 时中英两边的同名分区各加一条。
import { enUS } from "./messages/en-US";
import { zhCN } from "./messages/zh-CN";

export const messages = {
  "zh-CN": zhCN,
  "en-US": enUS,
} as const;

export type MessageKey = keyof (typeof messages)["zh-CN"];
