import React from "react";
import { X } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Combobox } from "@/components/app/combobox";

/**
 * 一串素材(插件工具的 `{"type": "array", "items": {"format": "asset"}}`)。
 *
 * 此前这种字段落到通用的 object 分支,渲染成一个写着 `[]` 的 JSON 文本框 —— 要用户手写一串素材 id。
 * 现在是挑出来的一排:每份一个可以移除的标签,后面一个选择器再加一份。顺序就是挑的顺序(插件按顺序用)。
 */
export function AssetListField({
  value,
  options,
  onChange,
}: {
  value: unknown;
  /** 可挑的素材(已按字段声明的素材种类筛过)。 */
  options: Array<{ value: string; label: string }>;
  onChange: (next: string[]) => void;
}) {
  const t = useI18n();
  const picked = Array.isArray(value) ? value.map(String).filter(Boolean) : [];
  const names = new Map(options.map((option) => [option.value, option.label]));
  const remaining = options.filter((option) => !picked.includes(option.value));
  return (
    <div className="grid min-w-0 gap-1.5" data-slot="asset-list">
      {picked.length > 0 && (
        <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
          {picked.map((id, index) => (
            <li
              key={`${id}-${index}`}
              className="inline-flex min-w-0 max-w-full items-center gap-1 rounded-md border border-border bg-field py-0.5 pl-2 pr-0.5 text-ui-xs text-foreground"
            >
              <span className="min-w-0 truncate" title={names.get(id) ?? id}>{names.get(id) ?? id}</span>
              <button
                type="button"
                aria-label={t("wfAssetListRemove").replace("{name}", names.get(id) ?? id)}
                className="grid size-5 shrink-0 cursor-pointer place-items-center rounded text-muted-foreground hover:bg-secondary hover:text-foreground"
                onClick={() => onChange(picked.filter((_, at) => at !== index))}
              >
                <X size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <Combobox
        value=""
        options={remaining}
        placeholder={t("wfAssetListAdd")}
        emptyText={t("cmdkEmpty")}
        className="w-full"
        onValueChange={(next) => next && onChange([...picked, next])}
      />
    </div>
  );
}
