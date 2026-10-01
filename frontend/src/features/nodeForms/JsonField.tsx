import React from "react";
import { toast } from "sonner";

import { useI18n } from "@/app/preferences";
import { CodeEditor } from "@/components/app/code-editor";

/** 还没填:没有值,或是空串 —— 「接上游」那一下会把字面量清成 `""`(workflows/connections 的 withDataInputBound),
 *  断开之后这一格存的就是它。按「还没填」显示成 `empty`,不是在框里摆一个字面的 `""`。 */
function shown(value: unknown, empty: unknown): string {
  return JSON.stringify(value === undefined || value === null || value === "" ? empty : value, null, 2);
}

/** object(JSON)字段:CodeMirror JSON 编辑,失焦解析回对象;非法给提示不写入。
    `empty` 是还没填时显示的形状:对象字段是 `{}`,一串对象(插件的数组入参)是 `[]`。 */
export function JsonField({
  value,
  onChange,
  empty = {},
}: {
  value: unknown;
  onChange: (parsed: unknown) => void;
  empty?: unknown;
}) {
  const t = useI18n();
  const [text, setText] = React.useState(() => shown(value, empty));
  // 上游(智能体改图)更新时回显,但不打断正在输入:仅当序列化值真变才重置。
  const synced = React.useRef(text);
  React.useEffect(() => {
    const next = shown(value, empty);
    if (next !== synced.current) {
      synced.current = next;
      setText(next);
    }
  }, [value]);
  return (
    <CodeEditor
      value={text}
      language="json"
      minHeight={34}
      gutter={false}
      onChange={setText}
      onBlur={() => {
        try {
          const parsed = text.trim() ? JSON.parse(text) : empty;
          synced.current = shown(parsed, empty);
          onChange(parsed);
        } catch {
          toast.error(t("wfBadJson"));
        }
      }}
    />
  );
}
