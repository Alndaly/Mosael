import * as React from "react";

/**
 * 行内编辑框的**草稿**:框里显示的字由框自己持有,改动再交给外面那份。
 *
 * ## 为什么不能直接 `value={外面那份}`
 *
 * 受控输入框要求「onChange 之后同一轮渲染里 value 就是新的」。React 在每次 input 事件结束时
 * 会把 DOM 的值**改回** props.value(controlled restore)—— props 还是旧的,DOM 就被写回旧字,
 * 等外面那份追上来再写一遍新字。英文输入看不出来;**输入法组词时每写一次 DOM 都会打断组词**,
 * 拼音字母被当成正文上屏(便签里敲出「daa skx」,见 boards/imeNote.dom.test)。
 *
 * 外面那份经常追不上同一轮:画板便签的字住在 React Flow 的节点里,而 React Flow 是在
 * **effect 里**把 nodes 抄进它自己的 store 的;服务端回执、防抖、改写(trim/截断)同理。
 * 所以规则收成一条:**框自己持有草稿**(同步更新,restore 时 DOM 和 props 永远相等),
 *
 *  · 组词期间只改草稿、不往外交 —— 拼音字母不进画布、不进撤销历史、不被自动保存送出去;
 *    `compositionend` 时把上屏的那段交出去一次;
 *  · 外面那份变了,**只在没在编辑(没聚焦、没组词)时采用** —— 正在打字的人才是这段字的主人,
 *    慢一拍的回声(或服务端那份)不能从他手里把字抢回去。
 *
 * 画布节点里、弹层里这类「值从别处绕一圈回来」的行内编辑都走它(`DraftTextarea` / `DraftInput`,
 * 要套现成样式组件的用 `useDraftText`)。
 */
type Field = HTMLInputElement | HTMLTextAreaElement;

type DraftHandlers<E extends Field> = Pick<
  React.DOMAttributes<E>,
  "onFocus" | "onBlur" | "onCompositionStart" | "onCompositionEnd"
>;

export type DraftTextOptions<E extends Field> = DraftHandlers<E> & {
  /** 外面那份。 */
  value: string;
  /** 用户改出来的新字 —— 组词期间不调,上屏后调一次;和上一次交出去的相同时不重复调。 */
  onValueChange: (next: string) => void;
};

export function useDraftText<E extends Field>({
  value,
  onValueChange,
  onFocus,
  onBlur,
  onCompositionStart,
  onCompositionEnd,
}: DraftTextOptions<E>) {
  const [draft, setDraft] = React.useState(value);
  const composing = React.useRef(false);
  const focused = React.useRef(false);
  //: 上一次交出去(或采用进来)的那份。外面的回声等于它时什么都不用做;交出去之前也拿它去重 ——
  //: 有的浏览器在 compositionend 之后还会补一次 input,同一段字不该存两遍。
  const settled = React.useRef(value);
  const latest = React.useRef(onValueChange);
  latest.current = onValueChange;
  const outside = React.useRef(value);
  outside.current = value;

  const adopt = React.useCallback((next: string) => {
    if (next === settled.current) return;
    settled.current = next;
    setDraft(next);
  }, []);

  React.useEffect(() => {
    if (!focused.current && !composing.current) adopt(value);
  }, [value, adopt]);

  const hand = (next: string): boolean => {
    if (next === settled.current) return false;
    settled.current = next;
    latest.current(next);
    return true;
  };

  return {
    value: draft,
    onChange: (event: React.ChangeEvent<E>) => {
      setDraft(event.target.value);
      if (!composing.current && !(event.nativeEvent as InputEvent).isComposing) hand(event.target.value);
    },
    onCompositionStart: (event: React.CompositionEvent<E>) => {
      composing.current = true;
      onCompositionStart?.(event);
    },
    onCompositionEnd: (event: React.CompositionEvent<E>) => {
      composing.current = false;
      const next = event.currentTarget.value;
      setDraft(next);
      hand(next);
      onCompositionEnd?.(event);
    },
    onFocus: (event: React.FocusEvent<E>) => {
      focused.current = true;
      onFocus?.(event);
    },
    onBlur: (event: React.FocusEvent<E>) => {
      focused.current = false;
      //: 离开时把框里的字交出去(组词被失焦打断、没来得及 compositionend 的那种);
      //: 这一趟什么都没改的话,编辑期间外面变过的那份现在采用进来。
      composing.current = false;
      if (!hand(event.currentTarget.value)) adopt(outside.current);
      onBlur?.(event);
    },
  };
}

type NativeProps<E extends Field, P> = Omit<P, "value" | "defaultValue" | "onChange"> & DraftTextOptions<E>;

/** 草稿式的多行框。用法同 `<textarea>`,只是 `value` + `onValueChange` 代替 `onChange`。 */
export const DraftTextarea = React.forwardRef<
  HTMLTextAreaElement,
  NativeProps<HTMLTextAreaElement, React.ComponentProps<"textarea">>
>(({ value, onValueChange, onFocus, onBlur, onCompositionStart, onCompositionEnd, ...props }, ref) => {
  const draft = useDraftText<HTMLTextAreaElement>({ value, onValueChange, onFocus, onBlur, onCompositionStart, onCompositionEnd });
  return <textarea ref={ref} {...props} {...draft} />;
});
DraftTextarea.displayName = "DraftTextarea";

/** 草稿式的单行框(不带样式 —— 要 `Input` 的样子就用 `useDraftText` 套在 `Input` 上)。 */
export const DraftInput = React.forwardRef<
  HTMLInputElement,
  NativeProps<HTMLInputElement, React.ComponentProps<"input">>
>(({ value, onValueChange, onFocus, onBlur, onCompositionStart, onCompositionEnd, ...props }, ref) => {
  const draft = useDraftText<HTMLInputElement>({ value, onValueChange, onFocus, onBlur, onCompositionStart, onCompositionEnd });
  return <input ref={ref} {...props} {...draft} />;
});
DraftInput.displayName = "DraftInput";
