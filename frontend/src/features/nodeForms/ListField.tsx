import React from "react";
import { X } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { AddRow } from "@/components/ui/add-row";
import { Button } from "@/components/ui/button";
import { Combobox } from "@/components/app/combobox";
import { bareRef } from "@/features/nodeForms/MapField";

/**
 * 一串值:插件入参里声明成数组(`"type": "array"`)、每一项是字符串或数字的那种。
 *
 * 此前这类字段拿到的是「名字 → 值」的映射编辑器(后端把 array 当 object),存下去的是 `{"a": …}`,
 * 交给插件的就不是数组。一行一项:每一项能从上游输出里挑(`{{llm-1.text}}`),也能手填。
 * 一行是一整串引用时,运行时把那一串拼进来(见后端 plugins.inputs.coerce)。
 */

/** 存着的值 → 行。不是数组的(还没填、或是一整串引用 `{{…}}`)给一行。 */
export function rowsFromList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((one) => (typeof one === "string" ? one : JSON.stringify(one)));
  if (typeof value === "string" && value.trim()) return [value];
  return [];
}

/**
 * 行 → 数组。空行丢掉(它对插件毫无意义);其余**一律存文字**,不在这里猜类型。
 *
 * 这一格装的是数、布尔还是字符串,只有 input_schema 的 `items.type` 说得准,而后端交给插件前正是按它转的
 * (plugins.inputs._as_list)。此前这里把「像数的」一律转成数:声明成字符串的 `"007"` 存成了 7,
 * 一串十九位的 id 存成浮点数丢了末几位 —— 存下去就回不来了。
 */
export function listFromRows(rows: string[]): string[] {
  return rows.filter((text) => text.trim());
}

/**
 * 存着的是「名字 → 值」的映射:旧版表单把数组当映射存下的写法(没被图升级迁移到的),或智能体写错了形状。
 * 按行渲染只会是一片空白,像没填 —— 运行时却会报「要的是一串值」。所以说出来,让人重新填一遍。
 */
export function isMapping(value: unknown): boolean {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function ListField({
  value,
  onChange,
  variables,
  maxItems,
}: {
  value: unknown;
  onChange: (next: string[]) => void;
  /** 上游能引用的输出,形如 `{{llm-1.text}}`。 */
  variables: string[];
  /** 最多几项(插件数组的 maxItems):到了就不再给「加一项」。 */
  maxItems?: number;
}) {
  const t = useI18n();
  // 本地保留行:「刚加的一行还空着」在数组里表示不出来,只按数组渲染的话新加的空行会当场消失。
  const [rows, setRows] = React.useState<string[]>(() => rowsFromList(value));
  const emitted = React.useRef(JSON.stringify(listFromRows(rowsFromList(value))));

  // 外面改了(撤销、智能体改图)才跟;自己发出去的那一版不跟,否则打字会被回流打断。
  React.useEffect(() => {
    const incoming = JSON.stringify(listFromRows(rowsFromList(value)));
    if (incoming === emitted.current) return;
    emitted.current = incoming;
    setRows(rowsFromList(value));
  }, [value]);

  const push = (next: string[]) => {
    setRows(next);
    const list = listFromRows(next);
    emitted.current = JSON.stringify(list);
    onChange(list);
  };

  const options = React.useMemo(
    () => variables.map((ref) => ({ value: ref, label: bareRef(ref) })),
    [variables],
  );

  return (
    <div className="grid gap-1.5">
      {isMapping(value) && rows.length === 0 && (
        <p className="m-0 text-ui-xs text-warning" role="note">
          {t("wfListGotMapping")}
        </p>
      )}
      {rows.map((row, index) => (
        <div className="grid grid-cols-[minmax(0,1fr)_24px] items-center gap-1" key={index}>
          <Combobox
            value={row}
            options={options}
            placeholder={t("wfListItem")}
            emptyText={t("cmdkEmpty")}
            allowCustomValue
            size="sm"
            className="w-full min-w-0 text-ui-xs"
            onValueChange={(next: string) => push(rows.map((one, i) => (i === index ? next : one)))}
          />
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label={t("delete")}
            onClick={() => push(rows.filter((_, i) => i !== index))}
          >
            <X size={12} />
          </Button>
        </div>
      ))}
      {maxItems !== undefined && rows.length >= maxItems ? (
        <p className="m-0 text-ui-xs text-muted-foreground" role="note">
          {t("wfItemsFull").replace("{n}", String(maxItems))}
        </p>
      ) : (
        <AddRow dense label={t("wfMapAdd")} onClick={() => setRows([...rows, ""])} />
      )}
    </div>
  );
}
