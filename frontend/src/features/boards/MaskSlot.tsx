import React from "react";
import { FolderOpen, Pencil, Plus } from "lucide-react";

import { assetThumbnailUrl } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { FallbackImage } from "@/components/ui/fallback-image";
import { MaskEditor } from "@/components/generation/MaskEditor";
import { IconButton } from "@/components/ui/icon-button";
import { MenuContent, MenuItem } from "@/components/ui/menu";
import { Popover, PopoverTrigger } from "@/components/ui/popover";
import { SourceAssetSlotPreview } from "@/features/boards/SourceAssetSlotPreview";

/** 蒙版槽里的一份(和面板里其余的槽同形:`from` = 顺着哪一格连过来的线挂上的)。 */
export interface MaskSource {
  assetId: string;
  from?: string;
}

/** 连进这一格、能拿来当蒙版的一张图。 */
export interface MaskCandidate {
  assetId: string;
  itemId?: string;
}

/**
 * 生成面板里的「蒙版」那一格(ADR 0107)。**按槽一行一行的那条和 ComfyUI 表单项那条都挂它**,蒙版的填法只写在这里。
 *
 * - 「+」是一个小菜单,三种填法:画一张(ADR 0057 的编辑器,底图是这一格的参考图)、用连进来的某张图(这就是
 *   「指定哪张是蒙版」—— 上游的图不会自己进这一格,见 NodeComposer.autoAssign)、从素材库挑。拖文件到「+」上照旧;
 * - 已经在这一格里的那张,点它是接着画(存下来是一张新素材,替换它);右上角是移除。
 */
export function MaskSlot({
  label,
  masks,
  limit,
  candidates,
  base,
  workspaceId,
  drop,
  onPickLibrary,
  onUseCandidate,
  onSaved,
  onRemove,
}: {
  /** 这一格叫什么(「蒙版」/ 第几张蒙版):照面板里别的槽的叫法。 */
  label: (index: number) => string;
  masks: MaskSource[];
  limit: number;
  /** 连进来、还没当成蒙版的图。 */
  candidates: MaskCandidate[];
  /** 画蒙版时铺在底下的那张(这一格挂着的第一张参考图 / 首帧);没有就是一块黑画布。 */
  base: { assetId: string; name: string } | null;
  workspaceId: string;
  /** 把拖进来的文件接到「+」上(面板的 SlotDrop:传进素材库、挂进这一格)。 */
  drop: (button: React.ReactElement) => React.ReactElement;
  onPickLibrary: () => void;
  onUseCandidate: (candidate: MaskCandidate) => void;
  /** 编辑器存好了一张:`replacing` 是接着画的那一张(没有 = 新加一张)。 */
  onSaved: (assetId: string, replacing?: string) => void;
  onRemove: (assetId: string) => void;
}) {
  const t = useI18n();
  const [menuOpen, setMenuOpen] = React.useState(false);
  //: 编辑器开着:接着画哪一张(null = 新画一张)。
  const [editing, setEditing] = React.useState<{ replacing: string | null } | null>(null);
  const room = masks.length < limit;

  return (
    <>
      {masks.map((one, index) => (
        <SourceAssetSlotPreview
          key={one.assetId}
          assetId={one.assetId}
          kind="image"
          label={label(index)}
          onEdit={() => setEditing({ replacing: one.assetId })}
          onRemove={() => onRemove(one.assetId)}
        />
      ))}
      {room && (
        <Popover open={menuOpen} onOpenChange={setMenuOpen}>
          {drop(
            <PopoverTrigger asChild>
              <IconButton
                size="icon-sm"
                variant="outline"
                label={label(masks.length)}
                aria-haspopup="menu"
                data-board-mask-add=""
                className="shrink-0 cursor-pointer border-dashed border-border-strong text-muted-foreground hover:border-primary hover:text-foreground"
              >
                <Plus size={13} />
              </IconButton>
            </PopoverTrigger>,
          )}
          <MenuContent label={label(masks.length)} align="start">
            <MenuItem
              icon={<Pencil size={14} />}
              label={t("maskDraw")}
              description={t("maskDrawHint")}
              onClick={() => {
                setMenuOpen(false);
                setEditing({ replacing: null });
              }}
            />
            {candidates.map((one, index) => (
              <MenuItem
                key={one.assetId}
                icon={<FallbackImage src={assetThumbnailUrl(one.assetId)} alt="" className="size-4 rounded-sm object-cover" />}
                label={t("boardMaskFromUpstream").replace("{n}", String(index + 1))}
                description={index === 0 ? t("boardMaskFromUpstreamHint") : undefined}
                onClick={() => {
                  setMenuOpen(false);
                  onUseCandidate(one);
                }}
              />
            ))}
            <MenuItem
              icon={<FolderOpen size={14} />}
              label={t("boardMaskFromLibrary")}
              onClick={() => {
                setMenuOpen(false);
                onPickLibrary();
              }}
            />
          </MenuContent>
        </Popover>
      )}
      <MaskEditor
        open={editing !== null}
        onOpenChange={(next) => {
          if (!next) setEditing(null);
        }}
        workspaceId={workspaceId}
        source={base}
        initial={editing?.replacing ? { assetId: editing.replacing, name: label(0) } : null}
        onDone={(asset) => {
          onSaved(asset.id, editing?.replacing ?? undefined);
          setEditing(null);
        }}
      />
    </>
  );
}
