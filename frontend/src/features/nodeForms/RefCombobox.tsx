import React from "react";

import { useI18n } from "@/app/preferences";
import { Combobox, type ComboboxOption } from "@/components/app/combobox";
import type { FieldSize } from "@/components/ui/control-size";
import { Truncate } from "@/components/ui/truncate";
import { RefEditor } from "@/features/nodeForms/RefEditor";
import { RefToken } from "@/features/nodeForms/RefToken";
import { refLabel, useRefCatalog } from "@/features/nodeForms/refCatalog";
import { bareRef, hasReference, isMixedTemplate, wholeRef } from "@/features/nodeForms/refDoc";
import { listedRefs, refProblemText } from "@/features/nodeForms/refLook";
import { cn } from "@/lib/utils";

/**
 * **「值或上游输出」:一格,填一个值,或挑一个上游的输出。** 具名输出、入参映射的值那一列(MapField)、一串值的
 * 每一项(ListField)、能写引用的下拉(挑素材 / 账号 / 选项,也收 `{{…}}`)、生成节点的「输入素材」都是它。
 *
 * 存下去的是 `{{节点.输出.子路径}}`;屏幕上:
 * - 整格一个引用 → 一枚引用标签「节点 · 输出 · 子路径」(见 refCatalog),不摆花括号。此前只有恰好在下拉清单里的
 *   (`{{save_note.note_id}}`)显示得干净,指向上游输出里**某个字段**的(`{{report.json.verdict}}`)不在清单里,
 *   退回原样显示那串模板;
 * - 指不到东西的引用(节点删了、改了名、写错了)→ 错误样式的标签,底下一句为什么 —— 不静默显示原文;
 * - 字和引用混写 → 和提示词同一个编辑器(引用是整块的标签),不摆双括号;
 * - 别的(字面量、清单里的一项)→ 照旧。
 *
 * 挑的时候:每个上游输出一项,输出声明了结构(JSON Schema)或上次运行交回过字段的,字段各一项排在它后面;
 * 没有的,在引用后面接着敲字段路径(`report.json.verdict`),清单最前给一项「引用 …」。
 *
 * **记着的那一项不在清单里**(清单是值的唯一来源时,见 `missingText`)—— 触发器照旧显示**存下来的那个值**
 * (清单里已经没有它,名字无从谈起,不编),换成警示色,底下一句让人重挑。这和 OptionPicker 的
 * `missingLabel` 是同一条规矩的两个出口:那里能写出它叫什么(生成选项还留着两层名字),这里写不出来,
 * 就只把事实说出来。
 */
const NO_OPTIONS: ComboboxOption[] = [];

export function RefCombobox({
  value,
  onValueChange,
  variables,
  options = NO_OPTIONS,
  literal = true,
  missingText,
  placeholder,
  emptyText,
  size,
  className,
}: {
  value: string;
  onValueChange: (next: string) => void;
  /** 上游能引用的输出,形如 `{{llm-1.text}}`。 */
  variables: readonly string[];
  /** 引用之外的选项(工作区里的素材、账号、固定选项……),排在引用前面 —— 挑现成的是常态。 */
  options?: ComboboxOption[];
  /** 清单和引用之外能不能手填一个字面量。挑资源的下拉不能(随手敲的一串字是个不存在的 id,只会运行时报错),
   *  只收引用;值本来就是一段字的(具名输出、入参)能。 */
  literal?: boolean;
  /**
   * 记着的那一项不在清单里时底下那句话。**只在这一格的清单是值的唯一来源时才有人给**(`literal` 为假:
   * 手填只收引用,清单之外的值本来就不合法);能随手填字面量的格子给了也不作数 —— 那种格子里"不在清单里"
   * 是常态,不是问题。清单还没到(空表)同样不下结论:那只是还不知道,不是"没有它"。
   */
  missingText?: string | null;
  placeholder?: string;
  emptyText?: string;
  size?: FieldSize;
  className?: string;
}) {
  const t = useI18n();
  const hostCatalog = useRefCatalog();
  //: 这一格的上游清单里列着的一定指得到(见 refLook.listedRefs)—— 混写编辑器里的引用标签用的是同一条。
  const catalog = React.useMemo(() => listedRefs(hostCatalog, variables), [hostCatalog, variables]);
  //: 编辑器自己发出去的最后一版。正在编辑器里改的时候,值暂时不再是混写(删掉了最后一个引用、清空了)也不换控件 ——
  //: 换了的话编辑器当场卸掉,光标没了。外面改了(撤销、智能体改图)才按值重新挑控件。
  const [typed, setTyped] = React.useState<string | null>(null);

  const refOptions = React.useMemo(
    () =>
      variables.flatMap((ref) => {
        const path = bareRef(ref);
        return [
          { value: ref, label: refLabel(catalog.look(path)) },
          ...catalog.fields(path).map((field) => ({ value: `{{${path}.${field}}}`, label: refLabel(catalog.look(`${path}.${field}`)) })),
        ];
      }),
    [variables, catalog],
  );
  const allOptions = React.useMemo(() => {
    const own = new Set(options.map((option) => option.value));
    return [...options, ...refOptions.filter((option) => !own.has(option.value))];
  }, [options, refOptions]);

  if (isMixedTemplate(value) || (typed !== null && typed === value)) {
    return (
      <RefEditor
        rows={1}
        value={value}
        variables={variables}
        label={placeholder}
        className="py-1 text-ui-xs"
        onChange={(next) => {
          setTyped(next);
          onValueChange(next);
        }}
      />
    );
  }

  const path = wholeRef(value);
  const look = path === null ? null : catalog.look(path);
  const problem = look?.problem ?? null;
  /**
   * 清单里没有这个值,而这一格的清单是**值的唯一来源**。
   *
   * 三个前提缺一不可:手填只收引用(`literal` 为假)、清单已经到了(空表说明还不知道)、值不是一段引用
   * (引用指不到东西有它自己那句,见 `problem`)。满足时值**照旧**显示 —— 清单里已经没有它,给不出名字。
   */
  const missing =
    !literal &&
    !problem &&
    path === null &&
    value.trim() !== "" &&
    options.length > 0 &&
    !allOptions.some((option) => option.value === value);
  const missingNote = missing ? (missingText ?? null) : null;

  /** 敲的是一段字段路径(`report.json.verdict`),前两段是上游的一个输出:给一项「引用 …」。 */
  const fieldPathOption = (query: string): ComboboxOption[] => {
    if (!/^[^\s.{}]+(\.[^\s.{}]+){2,}$/.test(query)) return [];
    const [node, output] = query.split(".");
    const ref = `{{${query}}}`;
    if (!variables.includes(`{{${node}.${output}}}`) || allOptions.some((option) => option.value === ref)) return [];
    return [{ value: ref, label: t("wfRefUseField").replace("{ref}", refLabel(catalog.look(query))) }];
  };

  return (
    <div className="grid min-w-0 gap-0.5">
      <Combobox
        value={value}
        options={allOptions}
        placeholder={placeholder}
        emptyText={emptyText ?? t("cmdkEmpty")}
        allowCustomValue
        acceptsCustomValue={literal ? undefined : hasReference}
        customValueLabel={literal ? undefined : (query) => t("wfUseReference").replace("{q}", query)}
        extraOptions={fieldPathOption}
        renderValue={() => {
          if (look && path !== null) return <RefToken path={path} look={look} />;
          //: 不在清单里:值照旧,只换警示色。给的是 `Truncate` 而不是一段裸字 —— `renderValue` 返回的东西
          //: 进的是触发器里那个位置(截断靠 `[&>span]:truncate` 的 CSS,而**悬停看不到全文**),放进去的
          //: 是一串三十几位的 id(见 combobox.tsx 的 `renderValue` 契约)。
          if (missingNote) {
            return (
              <Truncate data-missing="" className="text-warning">
                {value.trim()}
              </Truncate>
            );
          }
          //: 别的照旧回 undefined:combobox 自己退回 `selected?.label ?? value`(见它的 renderValue 契约)。
          return undefined;
        }}
        hint={problem ? refProblemText(t, problem) : (missingNote ?? path ?? undefined)}
        size={size}
        className={cn("w-full min-w-0", problem && "border-destructive", missingNote && "border-warning", className)}
        onValueChange={onValueChange}
      />
      {problem && (
        <small className="text-ui-2xs leading-[1.4] text-destructive" role="alert">
          {refProblemText(t, problem)}
        </small>
      )}
      {missingNote && (
        <small className="text-ui-2xs leading-[1.4] text-warning" role="note">
          {missingNote}
        </small>
      )}
    </div>
  );
}
