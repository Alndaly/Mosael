import * as React from "react";
import { ChevronDown } from "lucide-react";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { FIELD_TRIGGER_CLASS, FIELD_TRIGGER_CHEVRON } from "@/components/ui/field-trigger";
import { cn } from "@/lib/utils";

export type PickerOption = {
  value: string;
  label: string;
  /** 不展示但参与搜索的稳定名/别名(模型 id、供应商名)。展示名换成人话之后仍然搜得到。 */
  keywords?: string[];
  /** 只作用在这一项的行内样式 —— 用样式本身当信息的清单(字体选择器)。 */
  style?: React.CSSProperties;
};

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
  contentClassName,
  ariaLabel,
  placeholder,
  searchPlaceholder,
  emptyText,
  align = "start",
  ...rest
}: {
  value: string;
  onChange: (next: string) => void;
  options: PickerOption[];
  /** 触发器类名 —— 两个分支共用,长短列表在版面上必须**看不出区别**。 */
  className?: string;
  contentClassName?: string;
  ariaLabel?: string;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  align?: "start" | "center" | "end";
  /* 表单里的 FormControl 会把这几个挂到控件上(Radix Slot 克隆时注入)。不转交的话,
     错误提示和描述文字就和控件断了线 —— 读屏念到这一格时什么都没有。 */
} & Pick<React.ComponentProps<"button">, "id" | "aria-describedby" | "aria-invalid">) {
  const selected = options.find((one) => one.value === value);
  if (options.length > SEARCHABLE_THRESHOLD) {
    return (
      <SearchableSelect
        value={value}
        onValueChange={onChange}
        options={options}
        placeholder={placeholder}
        searchPlaceholder={searchPlaceholder}
        emptyText={emptyText}
        /* 浮层宽度不跟触发器:这些触发器是工具行里的小胶囊,对齐它等于把每个模型名折成三行。
           触发器比这宽时(设置弹层里的整格)再由调用方用 contentClassName 覆盖。 */
        contentClassName={cn("w-[min(320px,calc(100vw-16px))]", contentClassName)}
        trigger={
          /* 结构照抄 SelectTrigger:一个 span 一个 chevron。调用方那串 `[&>svg]:hidden`、
             `[&>span]:truncate` 才会同样落到实处,而不是只对其中一个分支生效。 */
          /* role=combobox 和 Select 的触发器一致 —— 换了实现不该换掉读屏里听到的东西。 */
          <button type="button" role="combobox" aria-label={ariaLabel} className={cn(FIELD_TRIGGER_CLASS, className)} {...rest}>
            <span className={cn("min-w-0 truncate", !selected && "text-muted-foreground")} style={selected?.style}>
              {selected?.label ?? placeholder ?? ""}
            </span>
            <ChevronDown className={FIELD_TRIGGER_CHEVRON} />
          </button>
        }
      />
    );
  }
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger aria-label={ariaLabel} className={className} {...rest}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent align={align} className={contentClassName}>
        {options.map((one) => (
          <SelectItem key={one.value} value={one.value} className="[overflow-wrap:anywhere]" style={one.style}>
            {one.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
