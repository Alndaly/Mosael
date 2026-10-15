import React from "react";
import { FileUp, FolderUp, Loader2, Paperclip } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";
import { MenuContent, MenuItem } from "@/components/ui/menu";
import { Popover, PopoverTrigger } from "@/components/ui/popover";
import type { ComposerAttachments } from "@/features/agent/composerAttachments";
import { folderFromInput } from "@/lib/folderFiles";

/**
 * 输入框的 📎:点开选「文件…」还是「文件夹…」(ADR 0059)。
 *
 * 浏览器的选择框一次只能选一种 —— 带 webkitdirectory 的只能选文件夹,不带的选不了文件夹 —— 所以是两个隐藏的
 * `<input>`、一张两行的菜单,不是一个按钮。压缩包走「文件…」。两个对话框(AI 工作台、画布助手)共用这一个,
 * 位置和能力才不会一边多一边少。
 */
export function ComposerAttachMenu({ attach, label }: { attach: ComposerAttachments; label: string }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const fileInput = React.useRef<HTMLInputElement | null>(null);
  const folderInput = React.useRef<HTMLInputElement | null>(null);
  const pick = (input: HTMLInputElement | null) => {
    setOpen(false);
    input?.click();
  };

  return (
    <>
      <input
        ref={fileInput}
        type="file"
        multiple
        hidden
        data-testid="composer-file-input"
        onChange={(event) => {
          void attach.accept(event.currentTarget.files);
          event.currentTarget.value = "";
        }}
      />
      <input
        ref={(node) => {
          folderInput.current = node;
          //: React 不认识这个属性,直接写在 DOM 上(Electron 和浏览器都支持;设置页导入技能同款)。
          node?.setAttribute("webkitdirectory", "");
        }}
        type="file"
        multiple
        hidden
        data-testid="composer-folder-input"
        onChange={(event) => {
          void attach.acceptFolder(folderFromInput(event.currentTarget.files));
          event.currentTarget.value = "";
        }}
      />
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <IconButton variant="ghost" size="icon-xs" label={label} aria-haspopup="menu" disabled={attach.uploading}>
            {attach.uploading ? <Loader2 size={14} className="animate-mosael-spin" /> : <Paperclip size={14} />}
          </IconButton>
        </PopoverTrigger>
        <MenuContent align="start" side="top" className="z-[120]" label={label}>
          <MenuItem
            icon={<FileUp size={14} />}
            label={t("composerAttachFiles")}
            description={t("composerAttachFilesHint")}
            onClick={() => pick(fileInput.current)}
          />
          <MenuItem
            icon={<FolderUp size={14} />}
            label={t("composerAttachFolder")}
            description={t("composerAttachFolderHint")}
            onClick={() => pick(folderInput.current)}
          />
        </MenuContent>
      </Popover>
    </>
  );
}
