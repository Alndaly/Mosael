import { useI18n } from "@/app/preferences";
import { Combobox } from "@/components/app/combobox";
import type { FieldSize } from "@/components/ui/control-size";
import { parseCustomSize } from "@/lib/generationCapabilities";

/**
 * 尺寸只是**推荐的几档、手填的也收**时的选择器(描述符的 `custom_size`,见 customSizeRule)。
 *
 * 推荐的几档照旧在下拉里;敲一个「宽x高」(`768x1024`、`768 × 1024`、`768*1024` 都认)就多出一项「使用这个」,
 * 选了存成规整的 `768x1024`。写法不对、或有一边比模型说的下限小,不给这一项 —— 和后端提交前的校验同一个判据。
 * AI 工作台、画板生成面板、工作流「AI 生成素材」节点用的是这一个。
 */
export function CustomSizePicker({
  value,
  options,
  minimum,
  ariaLabel,
  className,
  size,
  onChange,
}: {
  value: string;
  options: string[];
  minimum: number;
  ariaLabel?: string;
  className?: string;
  size?: FieldSize;
  onChange: (next: string) => void;
}) {
  const t = useI18n();
  return (
    <Combobox
      value={value}
      options={options.map((one) => ({ value: one, label: one }))}
      allowCustomValue
      acceptsCustomValue={(query) => parseCustomSize(query, minimum) !== null}
      searchPlaceholder={t("genSizeCustomPlaceholder")}
      ariaLabel={ariaLabel}
      className={className}
      size={size}
      onValueChange={(next) => onChange(parseCustomSize(next, minimum) ?? next)}
    />
  );
}
