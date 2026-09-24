import type { MessageKey } from "../i18n";

export type MessageParams = Record<string, string | number>;

const PREFIX = "i18n:";
const ENCODED = /^i18n:([A-Za-z0-9]+)(?: (\{.*\}))?$/s;

/**
 * 扩展自己的报错带的是**文案 key**,不是哪一种语言的句子。
 *
 * 报错要穿过「页面脚本 → 内容脚本 → 侧栏」几段消息通道,到侧栏时只剩一个字符串;而页面脚本
 * 不知道用户在侧栏里选的界面语言。所以 message 里编码 key 和参数,由侧栏用 `localizeMessage`
 * 按当前语言翻出来。这个模块只 import 类型,不把整张文案表打进页面脚本。
 */
export function localizedError(key: MessageKey, params: MessageParams = {}): Error {
  return new Error(PREFIX + key + (Object.keys(params).length ? ` ${JSON.stringify(params)}` : ""));
}

/** 解出 `localizedError` 编码的 key 和参数;不是这种格式(比如后端给的 detail)就返回 null。 */
export function decodeLocalizedMessage(message: string): { key: string; params: MessageParams } | null {
  const match = ENCODED.exec(message);
  if (!match) return null;
  try {
    return { key: match[1], params: match[2] ? (JSON.parse(match[2]) as MessageParams) : {} };
  } catch {
    return null;
  }
}
