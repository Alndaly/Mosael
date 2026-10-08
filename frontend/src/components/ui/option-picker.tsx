import * as React from "react";
import { ChevronDown } from "lucide-react";

import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SearchableSelect, type OptionSection } from "@/components/ui/searchable-select";
import type { FieldSize } from "@/components/ui/control-size";
import { fieldTriggerClass, FIELD_TRIGGER_CHEVRON } from "@/components/ui/field-trigger";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { cn } from "@/lib/utils";

export type PickerOption = {
  value: string;
  label: string;
  /** 不展示但参与搜索的稳定名/别名(模型 id、供应商名)。展示名换成人话之后仍然搜得到。 */
  keywords?: string[];
  /** 只作用在这一项的行内样式 —— 用样式本身当信息的清单(字体选择器)。 */
  style?: React.CSSProperties;
  /** 副标题,解释"选它会怎样"。短清单和可搜索那版都要渲染 —— 换个分支说法就没了不行。 */
  description?: string;
  /**
   * 行首的一张小图(模型文件的缩略图)。和 `description` 一样两个分支都画;只画在清单里,
   * 不进触发器 —— 触发器里那一枚由调用方经 `icon` 给(它知道选中的是哪一项、该多大)。
   */
  media?: React.ReactNode;
  /**
   * 分组标题(配音的「系统音色」「我的克隆音色」)。相邻的同名项归一组,顺序即传入顺序 —— 和 SearchableSelect
   * 同一个约定,两个分支都分组;没有标题的那几项不分组。
   */
  group?: string;
  /** 属于哪一小组(有表单的工作流的几个入口,ADR 0045 §7):只管搜索 —— 命中一行整个小组留着,见 SearchableSelect。
   *  不画小标题、不缩进,每一行自己是一个能选的入口。 */
  section?: OptionSection;
};

/** 相邻的同名 `group` 归成一组(不重排)。 */
function groupAdjacent(options: PickerOption[]): Array<[string, PickerOption[]]> {
  const out: Array<[string, PickerOption[]]> = [];
  for (const option of options) {
    const heading = option.group ?? "";
    const last = out[out.length - 1];
    if (last && last[0] === heading) last[1].push(option);
    else out.push([heading, [option]]);
  }
  return out;
}

/**
 * 「选项一多就该能搜」这条规矩的**唯一实现处**。
 *
 * 短列表用 Select:原生感、键盘首字母跳转、不占额外一行输入框 —— 三个宽高比之间加个搜索框
 * 是纯噪音。长列表用 SearchableSelect:模型/音色这类清单会长到十几二十项,列表里滚着找一个
 * 名字只差一个数字的条目(seedance-2.5-image-to-video / seedance-2.5-reference-to-video)
 * 是这个界面上最慢的一个动作。
 *
 * 分界线写在这里而不是各个调用点:抄一遍就意味着日后某处的模型清单长到 30 项也没人记得改。
 */
export const SEARCHABLE_THRESHOLD = 8;

export function OptionPicker({
  value,
  onChange,
  options,
  className,
  size,
  contentClassName,
  ariaLabel,
  icon,
  disabled,
  placeholder,
  searchPlaceholder,
  emptyText,
  align = "start",
  hint,
  missingLabel,
  ...rest
}: {
  value: string;
  onChange: (next: string) => void;
  options: PickerOption[];
  /** 触发器类名 —— 两个分支共用,长短列表在版面上必须**看不出区别**。 */
  className?: string;
  /** 触发器档位,和 `<Input size>`、`<Button size>` 同一把尺 —— 两个分支同一档。 */
  size?: FieldSize;
  /**
   * 值左侧的一枚装饰图标(说明这一格选的是什么)。
   *
   * **画在触发器里面,不在外面包一层。** 包在外面的话就有了两个盒子:hover 底色画在外层,
   * 而焦点环来自触发器 —— 于是同一个控件在悬停和聚焦时高亮出两个不同大小的方框,图标被环
   * 排除在外;左边紧贴图标没有内边距,右边却留着触发器自己的 px,左右不对称。放进来之后
   * 内边距、hover、焦点环共用同一个圆角框。
   */
  icon?: React.ReactNode;
  contentClassName?: string;
  ariaLabel?: string;
  /** 没得选的时候要说得出来,而不是给一个点开是空的下拉。 */
  disabled?: boolean;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  align?: "start" | "center" | "end";
  /** 触发器的悬停说明(为什么点不了、清单为什么是空的)。 */
  hint?: string | null;
  /**
   * 记着的那一项现在不在清单里(用不了,见 lib/generationCapabilities 的 chooseGenerationOption):触发器上写它(人话的名字 +
   * 「需要升级」/「用不了」,警示色),不写占位的「选择模型」—— 显示的就是记着的那个,不是空着、也不是别的。
   */
  missingLabel?: string | null;
  /* 表单里的 FormControl 会把这几个挂到控件上(Radix Slot 克隆时注入)。不转交的话,
     错误提示和描述文字就和控件断了线 —— 读屏念到这一格时什么都没有。 */
} & Pick<React.ComponentProps<"button">, "id" | "aria-describedby" | "aria-invalid">) {
  const selected = options.find((one) => one.value === value);
  const missing = !selected && Boolean(missingLabel);
  if (options.length > SEARCHABLE_THRESHOLD) {
    return (
      <SearchableSelect
        value={value}
        onValueChange={onChange}
        disabled={disabled}
        options={options}
        placeholder={placeholder}
        searchPlaceholder={searchPlaceholder}
        emptyText={emptyText}
        hint={hint}
        contentClassName={contentClassName}
        trigger={
          /* 结构照抄 SelectTrigger:一个 span 一个 chevron。调用方那串 `[&>svg]:hidden`、
             `[&>span]:truncate` 才会同样落到实处,而不是只对其中一个分支生效。 */
          /* role=combobox 和 Select 的触发器一致 —— 换了实现不该换掉读屏里听到的东西。 */
          <button type="button" role="combobox" aria-label={ariaLabel} disabled={disabled} className={cn(fieldTriggerClass(size), className)}
                  data-missing={missing ? "" : undefined} {...rest}>
            {icon}
            {/* 选中的值在触发器里会被截断(一个 checkpoint 文件名动辄四五十个字符):悬停看得到全名。 */}
            <Truncate className={cn(!selected && (missing ? "text-warning" : "text-muted-foreground"))} style={selected?.style}>
              {selected?.label ?? (missing ? missingLabel : null) ?? placeholder ?? ""}
            </Truncate>
            <ChevronDown className={FIELD_TRIGGER_CHEVRON} />
          </button>
        }
      />
    );
  }
  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      {/* 选项是服务端给的动态值:列表里单行截断、悬停看全文(SelectItem 的 truncate)。
          **触发器里的值自己画,不用 Radix 从清单里克隆过来的那一份**:克隆是从清单(浮层内容)里 portal 进来的,
          它的 React 上下文在清单那边 —— 浮层内容清掉了说明的范围(HintScopeReset),再加上值那一层
          pointer-events: none,被截断的名字悬停时哪条说明都不出。自己画的这一份在触发器的 Hint 里,
          被截断了全名就并进那条说明(外面还套着一条 Hint 时并进外面那条,见 tooltip.tsx 的 Hint)。 */}
      <Hint label={hint}>
        <SelectTrigger aria-label={ariaLabel} size={size} className={cn(missing && "data-[placeholder]:text-warning", className)}
                       data-missing={missing ? "" : undefined} {...rest}>
          {icon}
          <SelectValue placeholder={missing ? missingLabel : placeholder}>
            {selected ? <Truncate>{selected.label}</Truncate> : undefined}
          </SelectValue>
        </SelectTrigger>
      </Hint>
      <SelectContent align={align} className={contentClassName}>
        {groupAdjacent(options).map(([heading, rows]) => {
          const item = (one: PickerOption) => (
            <SelectItem
              key={one.value}
              value={one.value}
              truncate
              style={one.style}
              description={one.description}
              media={one.media}
              data-section={one.section?.key}
            >
              {one.label}
            </SelectItem>
          );
          const items = rows.map(item);
          return heading ? (
            <SelectGroup key={heading}>
              <SelectLabel>{heading}</SelectLabel>
              {items}
            </SelectGroup>
          ) : (
            <React.Fragment key="__ungrouped">{items}</React.Fragment>
          );
        })}
      </SelectContent>
    </Select>
  );
}
