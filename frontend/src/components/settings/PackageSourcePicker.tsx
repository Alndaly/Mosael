/**
 * 装包从哪个镜像拉:一个下拉 + 选「自定义地址」时长出的地址框。管理 → 下载源(pip / npm 两行)和插件连接上的
 * 「PyPI 镜像」「npm 镜像」共用这一个(见 backend domain/plugins/package_sources)。
 *
 * 预设由后端给(名字和地址都是),界面不写死一张镜像表。连接上多一项「跟随 Mosael(清华大学)」—— 空值就是它;
 * 管理页没有「跟随」,空值是官方源。
 *
 * 自定义地址**离开框的时候才存**:地址住在服务端,每敲一个字发一次请求会把字吞掉;没写 http(s):// 的由后端当场拒。
 */
import React from "react";

import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { useDraftText } from "@/components/ui/draft-text";
import { Input } from "@/components/ui/input";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { SETTINGS_FIELD_WIDTH } from "@/components/settings/settings-layout";

type Preset = components["schemas"]["PackageSourcePresetOut"];

const FOLLOW = "__follow__";
const CUSTOM = "__custom__";

export function PackageSourcePicker({ presets, value, onChange, followLabel, ariaLabel }: {
  presets: Preset[];
  /** 预设 key 或自定义地址;空 = 跟随(给了 followLabel 时)或官方源。 */
  value: string;
  onChange: (value: string) => void;
  /** 给了就多一项「跟随 Mosael(…)」,空值表示它。 */
  followLabel?: string;
  ariaLabel: string;
}) {
  const t = useI18n();
  const official = presets.find((preset) => !preset.url)?.value ?? "";
  const isPreset = presets.some((preset) => preset.value === value);
  const isCustom = Boolean(value) && !isPreset;
  //: 选了「自定义地址」、地址还没存。存下来之后值就是那个地址,由 isCustom 接着显示地址框。
  const [choosingCustom, setChoosingCustom] = React.useState(false);
  const selected = choosingCustom || isCustom ? CUSTOM : value || (followLabel ? FOLLOW : official);

  const choose = (next: string) => {
    if (next === CUSTOM) {
      setChoosingCustom(true);
      return;
    }
    setChoosingCustom(false);
    const stored = next === FOLLOW ? "" : next === official && !followLabel ? "" : next;
    if (stored !== value) onChange(stored);
  };

  return (
    <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
      <SearchableSelect
        className={SETTINGS_FIELD_WIDTH}
        value={selected}
        onValueChange={choose}
        options={[
          ...(followLabel ? [{ value: FOLLOW, label: t("pkgSourceFollow").replace("{name}", followLabel) }] : []),
          ...presets.map((preset) => ({ value: preset.value, label: preset.label, description: preset.url || undefined })),
          { value: CUSTOM, label: t("pkgSourceCustom") },
        ]}
      />
      {selected === CUSTOM && (
        <CustomAddress
          ariaLabel={ariaLabel}
          value={isCustom ? value : ""}
          onCommit={(url) => {
            const next = url.trim();
            if (next && next !== value) onChange(next);
          }}
        />
      )}
    </div>
  );
}

function CustomAddress({ value, onCommit, ariaLabel }: { value: string; onCommit: (value: string) => void; ariaLabel: string }) {
  const draft = useDraftText<HTMLInputElement>({ value, onValueChange: onCommit, commit: "blur" });
  return <Input className={SETTINGS_FIELD_WIDTH} aria-label={ariaLabel} placeholder="https://" autoFocus={!value} {...draft} />;
}
