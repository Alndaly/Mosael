import React from "react";
import { Plus, X } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Combobox } from "@/components/app/combobox";
import { Input } from "@/components/ui/input";

/**
 * 「名字 → 值」的映射:入参映射、请求头、具名输出、启动参数……
 *
 * 这类字段此前是一个 `{}` 的原始 JSON 框。要用上游节点的输出,得自己敲出
 * `{"topic": "{{llm-1.text}}"}` —— 键名要背、引号逗号要记,而**写错了直到运行才知道**:
 * JSON 少个引号是解析失败(还算好),引用名写错则一路静默地传个空值下去。
 *
 * 改成一行一对:左边填名字,右边从**上游节点的输出**里挑(也能手填字面量)。
 * 上游有什么在下拉里一目了然,不用回画布上一个个点开看输出变量叫什么。
 */

/** 值那一格既能挑引用,也能填字面量 —— 所以是可手填的下拉,不是纯选择器。 */
export interface MapRow {
  key: string;
  value: string;
}

/** 对象 → 行。**保持插入顺序**,不排序:用户看到的顺序就是他自己敲进去的顺序。 */
export function rowsFromObject(value: unknown): MapRow[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.entries(value as Record<string, unknown>).map(([key, one]) => ({
    key,
    // 值可能本来就不是字符串(数字、布尔)。原样显示,写回时再判断。
    value: typeof one === "string" ? one : JSON.stringify(one),
  }));
}

/**
 * 行 → 对象。
 *
 * 名字为空的行**丢掉**(它对后端毫无意义),但值为空的留着 —— 那通常是"名字先起好,值待填",
 * 删掉的话用户刚敲的名字会当场消失。
 *
 * 值尽量还原成原本的类型:`3` 存成数字而不是字符串 `"3"`。带 {{}} 的一律当字符串 ——
 * 那是模板,要留给引擎去插值。
 */
export function objectFromRows(rows: MapRow[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const row of rows) {
    const key = row.key.trim();
    if (!key) continue;
    const text = row.value;
    if (text.includes("{{")) {
      out[key] = text;
      continue;
    }
    const trimmed = text.trim();
    if (trimmed === "true" || trimmed === "false") out[key] = trimmed === "true";
    else if (trimmed !== "" && Number.isFinite(Number(trimmed))) out[key] = Number(trimmed);
    else out[key] = text;
  }
  return out;
}

export function MapField({
  value,
  onChange,
  variables,
  keyPlaceholder,
}: {
  value: unknown;
  onChange: (next: Record<string, unknown>) => void;
  /** 上游能引用的输出,形如 `{{llm-1.text}}`。 */
  variables: string[];
  keyPlaceholder?: string;
}) {
  const t = useI18n();
  // 本地保留行,因为「名字敲了一半、值还空着」在对象里根本表示不出来 —— 只按对象渲染的话,
  // 每敲一个字符行就会被重建,光标跳走。
  const [rows, setRows] = React.useState<MapRow[]>(() => rowsFromObject(value));
  const emitted = React.useRef(JSON.stringify(rowsFromObject(value)));

  // 外面改了(撤销、智能体改图)才跟;自己发出去的那一版不跟,否则打字会被回流打断。
  React.useEffect(() => {
    const incoming = JSON.stringify(rowsFromObject(value));
    if (incoming === emitted.current) return;
    emitted.current = incoming;
    setRows(rowsFromObject(value));
  }, [value]);

  const push = (next: MapRow[]) => {
    setRows(next);
    emitted.current = JSON.stringify(next.filter((row) => row.key.trim()));
    onChange(objectFromRows(next));
  };

  const options = React.useMemo(() => variables.map((ref) => ({ value: ref, label: ref })), [variables]);
  //: 还没被用掉的上游引用。已经用过的不再列 —— 列着只会让人以为可以加第二遍。
  const unused = React.useMemo(() => {
    const used = new Set(rows.map((row) => row.value));
    return variables.filter((ref) => !used.has(ref));
  }, [variables, rows]);

  return (
    <div className="grid gap-1.5">
      {/* 有行的时候给一排列头 —— 两列都是输入框,不说明哪列是什么就得靠猜。 */}
      {rows.length > 0 && (
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_24px] gap-1 text-ui-2xs text-muted-foreground">
          <span>{t("wfMapKey")}</span>
          <span>{t("wfMapValue")}</span>
          <span />
        </div>
      )}
      {rows.map((row, index) => (
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_24px] items-center gap-1" key={index}>
          <Input
            className="h-8 min-w-0 rounded-md text-ui-xs"
            value={row.key}
            placeholder={keyPlaceholder ?? t("wfMapKey")}
            onChange={(event) => push(rows.map((one, i) => (i === index ? { ...one, key: event.target.value } : one)))}
          />
          <Combobox
            value={row.value}
            options={options}
            placeholder={t("wfMapValue")}
            emptyText={t("cmdkEmpty")}
            // 手填是**常态**:值可以是上游引用,也可以是写死的字面量。
            allowCustomValue
            className="h-8 w-full min-w-0 text-ui-xs"
            onValueChange={(next: string) =>
              push(rows.map((one, i) => (i === index ? { ...one, value: next } : one)))
            }
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
      {/* **左对齐的小按钮,不是居中的大块。** 一行都没有时,居中的"加一项"孤零零悬在那儿,
          既不像表单也不像空状态 —— 它只是个次要操作,主路径是下面那排上游 chip:
          多数时候用户就是想把上一个节点的输出接进来,点一下就好,不用先加行再挑值。 */}
      <Button
        type="button"
        variant="ghost"
        size="xs"
        className="w-fit justify-start px-1.5"
        onClick={() => push([...rows, { key: "", value: "" }])}
      >
        <Plus size={12} />
        {t("wfMapAdd")}
      </Button>
      {/**
        * **上游有什么,直接摆出来。**
        *
        * 一行都没有的时候,这一栏只有一个"加一项" —— 用户看不出上游到底能给什么,得回画布上
        * 一个个点开看输出变量叫什么。别处(如子图的「对外输出」)早就把可用引用做成一排 chip 了,
        * 这里没有纯粹是漏了。
        *
        * 点一下就**连名带值加一行**:名字取输出名(`{{llm-1.text}}` → `text`),那多半就是他想要的,
        * 不合适再改。已经用过的不再列出来 —— 列着只会让人以为可以加第二遍。
        */}
      {unused.length > 0 && (
        <div className="grid gap-1 rounded-md border border-dashed border-border p-1.5">
          <span className="text-ui-2xs text-muted-foreground">{t("wfMapFromUpstream")}</span>
          <div className="flex flex-wrap gap-1">
          {unused.map((ref) => (
            <button
              key={ref}
              type="button"
              className="cursor-pointer rounded-md border-0 bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] px-1.5 py-0.5 font-mono text-ui-2xs text-primary transition-colors hover:bg-[color-mix(in_srgb,var(--primary)_20%,transparent)]"
              title={t("wfMapUseRef")}
              onClick={() => push([...rows, { key: suggestName(ref, rows), value: ref }])}
            >
              {ref.replace(/^\{\{|\}\}$/g, "")}
            </button>
          ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** `{{llm-1.text}}` → `text`;重名就跟上游节点名,再不行加序号。 */
export function suggestName(ref: string, rows: MapRow[]): string {
  const inner = ref.replace(/^\{\{|\}\}$/g, "");
  const [nodeId, output] = inner.split(".");
  const taken = new Set(rows.map((row) => row.key));
  for (const candidate of [output, `${nodeId}_${output}`.replace(/-/g, "_")]) {
    if (candidate && !taken.has(candidate)) return candidate;
  }
  let n = 2;
  while (taken.has(`${output}_${n}`)) n += 1;
  return `${output}_${n}`;
}
