/**
 * 自定义参数组的**语义化表单** —— 不写 JSON。
 *
 * 结构由后端 `/api/generation/capability-profile-schema` 驱动(34 个字段的键/形状/分组,
 * 见 backend domain/generation/custom_profiles.py):加一个字段只改后端一处,这个表单自动
 * 长出对应控件。这里**只有形状渲染器,没有字段知识** —— 字段知识抄过来一份,就会在加字段时
 * 悄悄漏掉,而那正是这个仓库一直在消灭的那种沉默。
 *
 * 渐进披露:可调参数先勾,可选值与默认值跟着勾出来的参数出现;上限与高级字段经「添加字段」
 * 按需请出来 —— 三十几个控件一次铺开,比 JSON 好不了多少。
 */
import React from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { AddRow } from "@/components/ui/add-row";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { isImeKeystroke } from "@/lib/shortcuts";

type Schema = components["schemas"]["CapabilityProfileSchemaOut"];
type Descriptor = Record<string, unknown>;

function useSchema(kind: "image" | "video") {
  return useQuery({
    queryKey: ["capability-profile-schema", kind],
    queryFn: () => api<Schema>(`/api/generation/capability-profile-schema?kind=${kind}`),
    staleTime: 10 * 60_000,
  });
}

/** 一串值的碎屑编辑器:回车添加,× 移除。numeric 时只收正整数。 */
function Chips({
  values,
  onChange,
  numeric,
  ariaLabel,
}: {
  values: Array<string | number>;
  onChange: (next: Array<string | number>) => void;
  numeric?: boolean;
  ariaLabel: string;
}) {
  const [text, setText] = React.useState("");
  const commit = () => {
    const raw = text.trim();
    if (!raw) return;
    if (numeric) {
      const value = Number(raw);
      if (!Number.isInteger(value) || value <= 0) return;
      if (!values.includes(value)) onChange([...values, value]);
    } else if (!values.includes(raw)) {
      onChange([...values, raw]);
    }
    setText("");
  };
  return (
    /* 和 Input 同高(min-h-10):它在版面上就是一格输入框,只是里面装的是碎屑。
       内容多到换行时再往下长 —— 所以是 min-h 不是 h。 */
    <div className="flex min-h-10 flex-wrap items-center gap-1 rounded-md border border-field-border bg-panel px-2 py-1.5">
      {values.map((value) => (
        <span key={String(value)} className="flex items-center gap-0.5 rounded bg-secondary px-1.5 py-px text-ui-xs text-foreground">
          {String(value)}
          <button
            type="button"
            aria-label={`${ariaLabel} ${value}`}
            className="cursor-pointer text-muted-foreground hover:text-foreground"
            onClick={() => onChange(values.filter((one) => one !== value))}
          >
            <X size={11} />
          </button>
        </span>
      ))}
      <input
        value={text}
        aria-label={ariaLabel}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (isImeKeystroke(event)) return;
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          }
        }}
        onBlur={commit}
        className="min-w-16 flex-1 border-0 bg-transparent p-0 text-ui-xs text-foreground outline-none"
      />
    </div>
  );
}

/** 「名字 → 一串值」或「名字 → 一个数」的行式编辑器(source_limits / parameter_choices 那几种)。 */
function MapRows({
  entries,
  onChange,
  names,
  valueKind,
  addLabel,
  ariaLabel,
  namePlaceholder,
}: {
  entries: Array<[string, unknown]>;
  onChange: (next: Array<[string, unknown]>) => void;
  /** 名字一列的候选(素材角色、已勾参数…)。可手输,候选只是少打字。 */
  names: string[];
  valueKind: "number" | "chips" | "int_chips";
  addLabel: string;
  ariaLabel: string;
  /** 名字那一列还没挑时显示什么 —— 「参数可选值」当占位符只是把标题又说了一遍。 */
  namePlaceholder: string;
}) {
  /* **正在编辑的行留在本地。**
     上层把行列表从描述符里**推导**出来(`Object.entries(value[key])`),而刚加的那一行还没有
     名字 —— 提交时被 `name.trim()` 过滤掉,描述符没变,重渲染推导出的还是原来那几行:点「加一行」
     什么都不发生。这不是按钮没绑事件,是草稿在一个存不下草稿的地方。
     所以这里自己拿着行,只把**有名字的**推上去;上层换了一份数据(载入已有的那份、切 kind)时
     再按它重新落一次 —— 判据是"上层那份和我上次推上去的不一样",否则会和用户正在打的字打架。 */
  const t = useI18n();
  const [rows, setRows] = React.useState<Array<[string, unknown]>>(entries);
  const pushed = React.useRef(JSON.stringify(entries));
  React.useEffect(() => {
    const incoming = JSON.stringify(entries);
    if (incoming !== pushed.current) {
      pushed.current = incoming;
      setRows(entries);
    }
  }, [entries]);

  const commit = (next: Array<[string, unknown]>) => {
    setRows(next);
    const named = next.filter(([name]) => name.trim());
    pushed.current = JSON.stringify(named);
    onChange(named);
  };
  const setEntry = (index: number, entry: [string, unknown]) =>
    commit(rows.map((one, i) => (i === index ? entry : one)));
  return (
    <div className="grid gap-1.5">
      {rows.map(([name, value], index) => (
        <div key={index} className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-1.5">
          <div className="grid gap-1">
            {/* 名字一列是**挑**,不是填:候选是一个封闭集合(勾出来的那几个参数、素材角色、
                填过的那几档分辨率),集合之外的名字保存时会被后端当作未知键退回来。
                此前它是 `<input list=…>` —— 浏览器自带的那个 datalist 下拉,箭头、字号、
                展开的浮层全都不是这套界面的长相,而且看上去像一格可以随便打字的输入框。 */}
            <OptionPicker
              ariaLabel={ariaLabel}
              value={name}
              placeholder={namePlaceholder}
              disabled={names.length === 0}
              onChange={(next) => setEntry(index, [next, value])}
              options={names.map((one) => ({ value: one, label: one }))}
            />
            {valueKind === "number" ? (
              <Input
                type="number"
                min={1}
                value={typeof value === "number" ? value : ""}
                aria-label={`${ariaLabel} ${name}`}
                onChange={(event) => setEntry(index, [name, Number(event.target.value) || 0])}
                className="bg-panel"
              />
            ) : (
              <Chips
                values={Array.isArray(value) ? (value as Array<string | number>) : []}
                numeric={valueKind === "int_chips"}
                ariaLabel={`${ariaLabel} ${name}`}
                onChange={(next) => setEntry(index, [name, next])}
              />
            )}
          </div>
          {/* 和字段那一层同一个长相:圆框。两处不一样的话,同一屏上就有两种"删掉这一行"。 */}
          <Button
            variant="ghost"
            size="icon-xs"
            /* 对齐到名字那一格的中线,不是整摞的顶端:这一列是"名字 + 取值"两层,
               items-start 会把叉顶到最上面,看起来像挂在两行之间。(40-28)/2 = 6px。 */
            className="mt-1.5 rounded-full border border-border hover:border-border-strong"
            /* 带上行号:这一格自己也有一个「×」(移除整格),两个按钮同名的话,读屏念出来
               一模一样 —— 而它们一个删一行、一个删一整格。 */
            aria-label={`${ariaLabel} ${t("genFormRemoveRow")} ${index + 1}`}
            onClick={() => commit(rows.filter((_, i) => i !== index))}
          >
            <X size={12} />
          </Button>
        </div>
      ))}
      <AddRow label={addLabel} onClick={() => commit([...rows, ["", valueKind === "number" ? 1 : []]])} />
    </div>
  );
}

/** 这张表单里**每一格**的外壳 —— 名字那一格也走它,不然同一屏上会有两种标签字号和两种输入框高度。 */
export function ProfileField({ label, children, onRemove }: { label: string; children: React.ReactNode; onRemove?: () => void }) {
  const t = useI18n();
  return (
    <div className="grid gap-1">
      <span className="flex items-center justify-between text-ui-xs font-medium text-muted-foreground">
        {label}
        {onRemove && (
          <button
            type="button"
            aria-label={`${label} ${t("genFormRemoveField")}`}
            /* 包一个圆框:光秃秃一个叉在一行文字右端,既看不出是可点的,也没有可点的边界。 */
            className="grid size-5 shrink-0 cursor-pointer place-items-center rounded-full border border-border text-faint transition-colors hover:border-border-strong hover:bg-secondary hover:text-foreground"
            onClick={onRemove}
          >
            <X size={11} />
          </button>
        )}
      </span>
      {children}
    </div>
  );
}

/**
 * 默认值那一组里的一行:名字在左,控件靠右。
 *
 * 控件给一个固定宽度而不是撑满:这一组里的取值都很短(一档尺寸、一个秒数、一个开关),撑满
 * 之后一个「是/否」会横跨整屏,读者要把视线从最左扫到最右才知道它是开还是关。
 */
function DefaultRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-10 items-center justify-between gap-3 border-b border-border/60 py-1 last:border-b-0">
      <span className="min-w-0 flex-1 truncate text-ui-sm text-foreground">{label}</span>
      {/* 不强行拉宽里面的东西:输入框和下拉本来就是 w-full,而开关是固定的 36px ——
          统一拉满会把一个「是/否」抻成 220px 的大条。justify-end 把它推到右端就够了。 */}
      <div className="flex w-[min(220px,50%)] shrink-0 justify-end">{children}</div>
    </div>
  );
}

/**
 * 一组的标题行。右侧可以挂一个动作 —— 「再加一个」属于这里,不属于列表末尾。
 *
 * `hint` 是**这一组和别的组差在哪**。四个组的标题都是两三个字(可选值/默认值/上限/特殊规则),
 * 光看标题分不出「可调参数」「可选值」「上限」各管什么 —— 而它们回答的是三个不同的问题:
 * 摆哪几个旋钮、每个旋钮有哪几档、这个端点的硬限制是什么。
 */
function GroupHeader({ title, hint, action }: { title: string; hint?: string; action?: React.ReactNode }) {
  return (
    <div className="grid gap-0.5">
      <div className="flex min-h-7 items-center justify-between gap-2">
        <span className="text-ui-xs font-semibold text-foreground">{title}</span>
        {action}
      </div>
      {hint && <span className="text-ui-xs leading-[1.45] text-muted-foreground">{hint}</span>}
    </div>
  );
}

export function CapabilityProfileForm({
  kind,
  value,
  onChange,
}: {
  kind: "image" | "video";
  value: Descriptor;
  onChange: (next: Descriptor) => void;
}) {
  const t = useI18n();
  const schema = useSchema(kind);
  const fields = schema.data?.fields ?? [];
  const shapeOf = (key: string) => fields.find((field) => field.key === key)?.shape ?? "";
  /* 键名由后端 schema 驱动,翻译键跟着拼 —— t 的键是静态联合类型,这里必须断言一次:
     后端加字段时 messages.ts 的 genField_* 要同步加(缺了界面就露出原始键名,看得见)。 */
  const labelOf = (key: string) => t(`genField_${key}` as Parameters<typeof t>[0]);
  /* 参数 chips 给人看的名字(尺寸/张数/参考图);键全集在 messages.ts,缺了会露 undefined ——
     那里是静态联合类型,漏加在 tsc 阶段就会红。 */
  const parameterLabel = (parameter: string) => t(`genParam_${parameter}` as Parameters<typeof t>[0]);

  const parameters = (value.parameter_keys as string[] | undefined) ?? [];
  /* 「这个参数的可选值装在哪个键里」由后端 schema 给(choices_key),不在这里再抄一份 ——
     抄漏的后果真机上看得见:声明了 quality 的可选值之后,没有任何地方可以设 default_quality,
     而后端一直收这个键。见 custom_profiles._CHOICES_KEY。 */
  const choicesKey = schema.data?.choices_key ?? {};
  const enumParameters = schema.data?.enum_parameters ?? [];
  /** 这个参数已经声明出来的可选值 —— 专属清单或 parameter_choices 里的那一槽。 */
  const choicesOf = (parameter: string): Array<string | number> | null => {
    const key = choicesKey[parameter];
    if (key) return (value[key] as Array<string | number> | undefined) ?? [];
    if (enumParameters.includes(parameter)) {
      const slot = (value.parameter_choices as Record<string, unknown> | undefined)?.[parameter];
      return Array.isArray(slot) ? (slot as Array<string | number>) : [];
    }
    return null;
  };
  /* 选了哪些**真有枚举值**的参数(质量/背景/输出格式那类,由后端按 kind 给出)——
     「参数可选值」一组只在他们当中挑行名。 */
  const enumCapableSelected = parameters.filter((parameter) => enumParameters.includes(parameter));
  const set = (key: string, next: unknown) => onChange({ ...value, [key]: next });
  const unset = (key: string) => {
    const next = { ...value };
    delete next[key];
    onChange(next);
  };
  const toggleParameter = (parameter: string) =>
    set(
      "parameter_keys",
      parameters.includes(parameter)
        ? parameters.filter((one) => one !== parameter)
        : [...parameters, parameter],
    );

  /* 「默认值」那一组有哪几行 —— 由 schema 推,不由名单定。
     判据是**这个旋钮存在**(勾了)且**它有档位可选**(或者它本来就不是选档位的形状,比如开关)。
     档位空着时不摆:一个点开是空的下拉,比没有它更糟。 */
  const defaultRows = fields
    .filter((field) => field.group === "defaults" && field.defaults_for)
    .map((field) => ({ key: field.key, parameter: field.defaults_for as string }))
    .filter(({ parameter }) => parameters.includes(parameter))
    .map(({ key, parameter }) => ({ key, options: choicesOf(parameter) }))
    .filter(({ options }) => options === null || options.length > 0);

  /* 上限与高级组:还没设值的字段进「添加字段」菜单,设了的排出来可移除。 */
  /* **「打开了这一格」和「这一格有值」是两件事。**
     此前只看后者:清空一格(或者刚点「加一行」而那一行还没填完)时描述符里的键被 unset,
     整格随即从界面上消失 —— 用户点的是"加一行",看到的是"这一项没了"。
     打开的状态留在本地,只有那个 × 才关掉它。 */
  const [opened, setOpened] = React.useState<string[]>([]);
  const isOpen = (key: string) => value[key] !== undefined || opened.includes(key);
  const openField = (key: string) => {
    setOpened((current) => (current.includes(key) ? current : [...current, key]));
    set(key, initialFor(shapeOf(key)));
  };
  const closeField = (key: string) => {
    setOpened((current) => current.filter((one) => one !== key));
    unset(key);
  };
  const groupFields = (group: string) => {
    const all = fields.filter((field) => field.group === group);
    return { active: all.filter((field) => isOpen(field.key)), idle: all.filter((field) => !isOpen(field.key)) };
  };

  const renderGeneric = (key: string) => {
    const shape = shapeOf(key);
    const current = value[key];
    if (shape === "str_list" || shape === "int_list") {
      return (
        <Chips
          values={Array.isArray(current) ? (current as Array<string | number>) : []}
          numeric={shape === "int_list"}
          ariaLabel={labelOf(key)}
          onChange={(next) => (next.length ? set(key, next) : unset(key))}
        />
      );
    }
    if (shape === "positive_int" || shape === "int") {
      return (
        <Input
          type="number"
          min={1}
          value={typeof current === "number" ? current : ""}
          aria-label={labelOf(key)}
          onChange={(event) => set(key, Number(event.target.value) || undefined)}
          className="bg-panel"
        />
      );
    }
    if (shape === "bool") {
      return <Switch checked={current === true} aria-label={labelOf(key)} onCheckedChange={(next) => set(key, next)} />;
    }
    if (shape === "str") {
      return (
        <Input
          value={typeof current === "string" ? current : ""}
          aria-label={labelOf(key)}
          onChange={(event) => set(key, event.target.value)}
          className="bg-panel"
        />
      );
    }
    if (shape === "str_to_int" || shape === "str_to_str_list" || shape === "str_to_int_list" || shape === "str_list_list") {
      const isMap = shape !== "str_list_list";
      const entries = isMap
        ? Object.entries((current as Record<string, unknown> | undefined) ?? {})
        : ((current as unknown[] | undefined) ?? []).map((group) => ["", group] as [string, unknown]);
      const names =
        key === "parameter_choices" ? parameters
        : key === "duration_by_resolution" ? ((value.resolutions as string[] | undefined) ?? [])
        : (schema.data?.source_roles ?? []);
      const commit = (next: Array<[string, unknown]>) => {
        if (isMap) {
          const obj = Object.fromEntries(next.filter(([name]) => name.trim()));
          Object.keys(obj).length ? set(key, obj) : unset(key);
        } else {
          const groups = next.map(([, group]) => group).filter((group) => Array.isArray(group) && group.length);
          groups.length ? set(key, groups) : unset(key);
        }
      };
      return (
        <MapRows
          entries={entries}
          names={names}
          valueKind={shape === "str_to_int" ? "number" : shape === "str_to_int_list" ? "int_chips" : "chips"}
          addLabel={t("genFormAddRow")}
          ariaLabel={labelOf(key)}
          namePlaceholder={t("genFormPickName")}
          onChange={commit}
        />
      );
    }
    return null;
  };

  return (
    <div className="grid gap-4">
      {/* 可调参数:只勾这个端点真会接受的 —— 勾了它不收,请求发出去被供应商拒掉。
          候选已经按 kind 过滤:image 的表单里不会出现 video 专属的时长与首尾帧。 */}
      <ProfileField label={t("genField_parameter_keys")}>
        <div className="flex flex-wrap gap-1">
          {(schema.data?.parameters ?? []).map((parameter) => (
            <button
              key={parameter}
              type="button"
              title={parameter}
              onClick={() => toggleParameter(parameter)}
              className={cn(
                "cursor-pointer rounded-md border px-1.5 py-0.5 text-ui-xs transition-colors",
                parameters.includes(parameter)
                  ? "border-primary bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-foreground"
                  : "border-border bg-panel text-muted-foreground hover:text-foreground",
              )}
            >
              {parameterLabel(parameter)}
            </button>
          ))}
        </div>
      </ProfileField>

      {/* 可选值:跟着勾出来的参数出现。「参数可选值」只在选了真有枚举的参数时才有意义 —
          没选的时候摆一个空行编辑器,看着像坏掉的。 */}
      {parameters.some((parameter) => choicesKey[parameter]) || enumCapableSelected.length > 0 ? (
        <div className="grid gap-2.5 border-t border-border pt-3">
          <GroupHeader title={t("genGroup_choices")} hint={t("genGroupHint_choices")} />
          {parameters.map((parameter) => {
            const listKey = choicesKey[parameter];
            if (!listKey) return null;
            return (
              <ProfileField key={listKey} label={labelOf(listKey)}>
                <Chips
                  values={(value[listKey] as Array<string | number> | undefined) ?? []}
                  numeric={listKey === "duration_seconds"}
                  ariaLabel={labelOf(listKey)}
                  onChange={(next) => (next.length ? set(listKey, next) : unset(listKey))}
                />
              </ProfileField>
            );
          })}
          {enumCapableSelected.length > 0 && (
            <ProfileField label={labelOf("parameter_choices")}>
              <MapRows
                entries={Object.entries((value.parameter_choices as Record<string, unknown> | undefined) ?? {})}
                names={enumCapableSelected}
                valueKind="chips"
                addLabel={t("genFormAddRow")}
                ariaLabel={labelOf("parameter_choices")}
                namePlaceholder={t("genFormPickParameter")}
                onChange={(next) => {
                  const obj = Object.fromEntries(next.filter(([name]) => name.trim()));
                  Object.keys(obj).length ? set("parameter_choices", obj) : unset("parameter_choices");
                }}
              />
            </ProfileField>
          )}
        </div>
      ) : null}

      {/* 默认值:**跟着勾出来的旋钮长**,而不是一张写死的名单。
          此前只认 size / resolution / aspect_ratio / duration / 两个开关 —— 于是声明了
          quality 的可选值之后,没有任何地方可以设 default_quality,而后端一直收这个键。
          现在每一格从 schema 的 defaults 组里来,「这一格是谁的默认值」也由 schema 说
          (defaults_for)。有档位可选的给下拉(选不回来的值不存在),其余按形状给控件。 */}
      {defaultRows.length > 0 && (
        <div className="grid gap-2.5 border-t border-border pt-3">
          <GroupHeader title={t("genGroup_defaults")} hint={t("genGroupHint_defaults")} />
          {/* 每一项一整行:名字在左,控件靠右。
              此前是两列格子,而这一组里控件宽窄差得极远(一个下拉、一个开关)—— 开关独占半格,
              左边空着一大片;只有一项时更明显,整组看起来像没排完。一行一项之后,行宽固定、
              控件右端对齐,加多少项都还是同一列。 */}
          <div className="grid gap-1">
            {defaultRows.map(({ key, options }) => (
              <DefaultRow key={key} label={labelOf(key)}>
                {options ? (
                  <OptionPicker
                    ariaLabel={labelOf(key)}
                    value={value[key] !== undefined ? String(value[key]) : String(options[0])}
                    onChange={(next) => set(key, shapeOf(key) === "int" ? Number(next) : next)}
                    options={options.map((one) => ({ value: String(one), label: String(one) }))}
                  />
                ) : (
                  renderGeneric(key)
                )}
              </DefaultRow>
            ))}
          </div>
        </div>
      )}

      {/* 上限、特殊规则:按需请出来,不一次铺开。
          **分两组,不合成一组。** 后端本来就把它们分开(custom_profiles._FIELD_GROUPS),
          而合起来叫「上限与高级」之后,「必需素材」「支持音频」这些既不是上限也说不上高级的
          字段全都落在一个说不着它们的标题底下 —— 读者当然分不出这一组和上面那几组的区别。 */}
      {(["limits", "advanced"] as const).map((group) => {
        const { active, idle } = groupFields(group);
        if (active.length === 0 && idle.length === 0) return null;
        return (
          <div className="grid gap-2.5 border-t border-border pt-3" key={group}>
            {/* 「再加一个」挂在组头上,不排在列表最末 —— 排在末尾的话,字段加得越多,下一次
                添加就要往下走得越远;而且它长得和一格空表单一模一样,像是有一项没填完。 */}
            <GroupHeader
              title={t(`genGroup_${group}` as Parameters<typeof t>[0])}
              hint={t(`genGroupHint_${group}` as Parameters<typeof t>[0])}
              action={
                idle.length > 0 ? (
                  <OptionPicker
                    ariaLabel={t("genFormAddField")}
                    placeholder={t("genFormAddField")}
                    value=""
                    onChange={(key) => key && openField(key)}
                    options={idle.map((field) => ({ value: field.key, label: labelOf(field.key) }))}
                    className="h-7 w-auto gap-1 px-2 text-ui-xs text-muted-foreground"
                    contentClassName="max-w-[min(420px,calc(100vw-32px))]"
                    align="end"
                  />
                ) : undefined
              }
            />
            {active.map((field) => (
              <ProfileField key={field.key} label={labelOf(field.key)} onRemove={() => closeField(field.key)}>
                {renderGeneric(field.key)}
              </ProfileField>
            ))}
          </div>
        );
      })}
    </div>
  );
}

function initialFor(shape: string): unknown {
  if (shape === "str_list" || shape === "str_list_list") return [];
  if (shape === "int_list") return [];
  if (shape === "positive_int" || shape === "int") return 1;
  if (shape === "bool") return false;
  if (shape === "str") return "";
  return {};
}
