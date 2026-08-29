import React from "react";

/**
 * 在一个普通 textarea 里用 `@` 引用素材。
 *
 * **不引入富文本编辑器。** 工作流那边的 `@` 是 TipTap 插件,因为它要在文档里留下一个不可
 * 拆分的引用节点;而这里的诉求小得多:挑一份素材,把它挂到这次生成的输入上。提示词本身
 * 仍然是一段纯文字 —— 为这件事换掉输入框,代价是光标、撤销、输入法全部要重新对一遍。
 *
 * 所以这里只做三件事:**看光标前有没有一个正在打的 `@词`**、把候选筛出来、选中之后把那段
 * `@词` 从文字里抹掉(素材通过 onPick 挂到别处去,不留在提示词里 —— 留着的话模型会把
 * 「@猫.png」当成描述的一部分念出来)。
 */
export interface MentionState {
  /** 正在打的那个词(不含 @)。null = 现在没有在打。 */
  query: string | null;
  /** 键盘选中的候选下标 —— 上下键移动,回车确认。 */
  index: number;
  setIndex: (index: number) => void;
  /** 输入变化时调一次:更新「是不是在打 @」。 */
  onChange: (value: string, caret: number) => void;
  /** 选中一个候选:把 `@词` 从文字里抹掉,返回新的文字与新的光标位置。 */
  take: (value: string) => { text: string; caret: number };
  close: () => void;
}

/** 光标前那段 `@词` 的起止。**要求 @ 前面是行首或空白** —— 不然邮箱、`a@b` 也会触发。 */
export function mentionRange(value: string, caret: number): { start: number; query: string } | null {
  const before = value.slice(0, caret);
  const at = before.lastIndexOf("@");
  if (at < 0) return null;
  if (at > 0 && !/\s/.test(before[at - 1])) return null;
  const query = before.slice(at + 1);
  // 词里不能有空白或换行:打完 @ 又敲了空格,说明他不是在挑素材。
  if (/\s/.test(query)) return null;
  return { start: at, query };
}

export function useAssetMentions(): MentionState {
  const [query, setQuery] = React.useState<string | null>(null);
  const [index, setIndex] = React.useState(0);
  const range = React.useRef<{ start: number; caret: number } | null>(null);

  const onChange = React.useCallback((value: string, caret: number) => {
    const found = mentionRange(value, caret);
    if (!found) {
      range.current = null;
      setQuery(null);
      return;
    }
    range.current = { start: found.start, caret };
    setQuery(found.query);
    setIndex(0);
  }, []);

  const take = React.useCallback((value: string) => {
    const current = range.current;
    if (!current) return { text: value, caret: value.length };
    const text = value.slice(0, current.start) + value.slice(current.caret);
    range.current = null;
    setQuery(null);
    return { text, caret: current.start };
  }, []);

  const close = React.useCallback(() => {
    range.current = null;
    setQuery(null);
  }, []);

  return { query, index, setIndex, onChange, take, close };
}
