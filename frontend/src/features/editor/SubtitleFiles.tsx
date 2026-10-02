import React from "react";
import { useMutation } from "@tanstack/react-query";
import { FileDown, FileUp } from "lucide-react";
import { toast } from "sonner";

import { exportSubtitleFile, type Sequence, type SubtitleFileFormat } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { PILL } from "@/features/editor/pill";
import { saveBlobToDisk } from "@/lib/download";

//: 「导入到一条新字幕轨」在下拉里的值(Select 不收空串)。
const NEW_TRACK = "__new__";
type Line = "all" | "first" | "last";

/**
 * 字幕轨 ⇄ .srt / .vtt。导出:选轨、选格式,双语字幕(两行)可以只写原文或只写译文;
 * 导入:默认落到一条新字幕轨(不碰已有的),也可以选一条现有的轨、勾「替换」换掉它原来的字幕。
 * 读文件(编码、换行、时间码、标记、重叠)都在后端(media/subtitle_files),这里只交文件。
 */
export function SubtitleFiles({
  sequence,
  onImport,
  importing,
}: {
  sequence: Sequence;
  onImport: (file: File, options: { trackId?: string; replace?: boolean }) => void;
  importing?: boolean;
}) {
  const t = useI18n();
  const tracks = React.useMemo(
    () => (sequence.tracks ?? []).filter((track) => track.kind === "subtitle").sort((a, b) => a.position - b.position),
    [sequence],
  );
  const withCues = tracks.filter((track) => (track.clips ?? []).length > 0);
  const [exportOpen, setExportOpen] = React.useState(false);
  const [importOpen, setImportOpen] = React.useState(false);
  const [exportTrack, setExportTrack] = React.useState("");
  const [format, setFormat] = React.useState<SubtitleFileFormat>("srt");
  const [line, setLine] = React.useState<Line>("all");
  const [importTrack, setImportTrack] = React.useState(NEW_TRACK);
  const [replace, setReplace] = React.useState(false);
  const fileInput = React.useRef<HTMLInputElement>(null);

  const chosenExport = withCues.find((track) => track.id === exportTrack) ?? withCues[0];
  const bilingual = (chosenExport?.clips ?? []).some((clip) => (clip.text_override ?? "").trim().includes("\n"));
  const download = useMutation({
    mutationFn: async () => {
      const blob = await exportSubtitleFile(sequence.id, chosenExport!.id, format, bilingual ? line : "all");
      saveBlobToDisk(blob, `${sequence.name}.${format}`);
    },
    onSuccess: () => setExportOpen(false),
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <>
      <Popover open={importOpen} onOpenChange={setImportOpen}>
        <PopoverTrigger asChild>
          <button type="button" className={PILL} title={t("subtitleFileImportHint")}>
            <FileUp size={12} /> {t("subtitleFileImport")}
          </button>
        </PopoverTrigger>
        <PopoverContent className="flex w-[220px] flex-col gap-2 p-2.5 [&>strong]:text-ui-sm" align="end">
          <strong>{t("subtitleFileImport")}</strong>
          <label className="grid gap-1 text-xs text-muted-foreground">
            <span>{t("subtitleFileImportTo")}</span>
            <Select value={importTrack} onValueChange={setImportTrack}>
              <SelectTrigger aria-label={t("subtitleFileImportTo")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NEW_TRACK}>{t("subtitleFileNewTrack")}</SelectItem>
                {tracks.map((track) => (
                  <SelectItem key={track.id} value={track.id}>{track.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
          {importTrack !== NEW_TRACK && (
            <label className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>{t("subtitleFileReplace")}</span>
              <Switch checked={replace} onCheckedChange={setReplace} />
            </label>
          )}
          <input
            ref={fileInput}
            type="file"
            accept=".srt,.vtt"
            className="hidden"
            aria-label={t("subtitleFileChoose")}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (!file) return;
              onImport(file, importTrack === NEW_TRACK ? {} : { trackId: importTrack, replace });
              setImportOpen(false);
            }}
          />
          <Button size="sm" loading={importing} onClick={() => fileInput.current?.click()}>
            <FileUp size={13} /> {t("subtitleFileChoose")}
          </Button>
        </PopoverContent>
      </Popover>
      {chosenExport && (
        <Popover open={exportOpen} onOpenChange={setExportOpen}>
          <PopoverTrigger asChild>
            <button type="button" className={PILL} title={t("subtitleFileExport")}>
              <FileDown size={12} /> {t("subtitleFileExport")}
            </button>
          </PopoverTrigger>
          <PopoverContent className="flex w-[220px] flex-col gap-2 p-2.5 [&>strong]:text-ui-sm" align="end">
            <strong>{t("subtitleFileExport")}</strong>
            {withCues.length > 1 && (
              <label className="grid gap-1 text-xs text-muted-foreground">
                <span>{t("subtitleDubTrack")}</span>
                <Select value={chosenExport.id} onValueChange={setExportTrack}>
                  <SelectTrigger aria-label={t("subtitleDubTrack")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {withCues.map((track) => (
                      <SelectItem key={track.id} value={track.id}>{track.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
            )}
            <label className="grid gap-1 text-xs text-muted-foreground">
              <span>{t("subtitleFileFormat")}</span>
              <Select value={format} onValueChange={(next) => setFormat(next as SubtitleFileFormat)}>
                <SelectTrigger aria-label={t("subtitleFileFormat")}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="srt">SRT</SelectItem>
                  <SelectItem value="vtt">WebVTT</SelectItem>
                </SelectContent>
              </Select>
            </label>
            {/* 只在真有双语字幕时问 —— 单语字幕摆一个「写哪一行」只会让人以为漏了什么。 */}
            {bilingual && (
              <label className="grid gap-1 text-xs text-muted-foreground">
                <span>{t("subtitleFileLine")}</span>
                <Select value={line} onValueChange={(next) => setLine(next as Line)}>
                  <SelectTrigger aria-label={t("subtitleFileLine")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{t("subtitleFileLineAll")}</SelectItem>
                    <SelectItem value="first">{t("subtitleFileLineFirst")}</SelectItem>
                    <SelectItem value="last">{t("subtitleFileLineLast")}</SelectItem>
                  </SelectContent>
                </Select>
              </label>
            )}
            <Button size="sm" loading={download.isPending} onClick={() => download.mutate()}>
              <FileDown size={13} /> {t("subtitleFileExport")}
            </Button>
          </PopoverContent>
        </Popover>
      )}
    </>
  );
}
