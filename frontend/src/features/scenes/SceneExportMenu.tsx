import { Download } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

/**
 * 「导出文件」:把场景**作为文件**带走 —— GLB 给别的 3D 软件,JSON 是这份场景本身。
 *
 * 这里只有这两样。存画面 / 预览视频到素材库、拿构图或首尾帧去生成,都在「生成素材」那个弹层里:
 * 此前这份菜单把那五项又抄了一遍(三条「→ 图片 / 视频生成」、两条「→ 素材库」),同一件事两个入口,
 * 而「导出文件」这个名字装不下它们。
 */
export function SceneExportMenu({
  disabled,
  onExportGlb,
  onExportJson,
}: {
  disabled: boolean;
  onExportGlb: () => void;
  onExportJson: () => void;
}) {
  const t = useI18n();
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" disabled={disabled}>
          <Download size={15} />
          {t("sceneExportFiles")}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="scene-export">
        <button type="button" onClick={onExportGlb}>
          {t("sceneExportGlb")}
        </button>
        <button type="button" onClick={onExportJson}>
          {t("sceneExportJson")}
        </button>
      </PopoverContent>
    </Popover>
  );
}
