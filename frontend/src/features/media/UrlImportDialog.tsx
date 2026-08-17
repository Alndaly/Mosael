import React from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link2, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { importFromUrl, listBrowserProfiles, probeUrl, type UrlProbe, type Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { NONE, optionalValue } from "@/components/ui/selectSentinel";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { knownBestHeight, qualityOptions } from "@/features/media/urlImportQuality";
import { toSection } from "@/features/media/urlImportTime";
import { formatTimecode } from "@/domain/timeline/geometry";
import { cn } from "@/lib/utils";

/**
 * 从链接导入素材。
 *
 * **先探再下**:一个链接可能是一条视频,也可能是一整个播放列表(几百条、几十 GB)。粘完先探
 * 元数据,把清单摆出来勾 —— 直接开下在单条时顺手,在播放列表上就是一次没人要的批量下载。
 *
 * **音频 / 视频在下载前选**,不是下完再抽:只要人声去转写的人,不该为此付几百 MB 和一次转码。
 */
export function UrlImportDialog({
  open,
  onOpenChange,
  workspace,
  projectId,
  onQueued,
}: {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  workspace: Workspace;
  projectId?: string | null;
  onQueued?: () => void;
}) {
  const t = useI18n();
  const [url, setUrl] = React.useState("");
  const [listing, setListing] = React.useState<UrlProbe | null>(null);
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [kind, setKind] = React.useState<"video" | "audio">("video");
  //: 画质上限。0 = 不限 —— 4K 素材动辄几个 GB,而多数剪辑只需要 1080p。
  const [maxHeight, setMaxHeight] = React.useState(0);
  //: 只要某一段。**只在单条时给** —— 同一个时间段套在不同视频上,截出来的是各不相干的片段。
  const [sectionStart, setSectionStart] = React.useState("");
  const [sectionEnd, setSectionEnd] = React.useState("");
  //: 列表翻页的起点。频道能有上万条,而一次探 200 条已经要翻好几页。
  const [pageStart, setPageStart] = React.useState(1);
  //: 借哪个登录身份。会员视频、私享列表不带登录态就只能看到"不可用" —— 而这个应用本来就把
  //: 所有持久登录攒在浏览器池里,没有理由让用户去别处导一份 cookie 出来。
  const [profileId, setProfileId] = React.useState(NONE);
  const profiles = useQuery({
    queryKey: ["browser-profiles", workspace.id],
    queryFn: () => listBrowserProfiles(workspace.id),
    enabled: open,
  });

  React.useEffect(() => {
    if (!open) {
      setUrl("");
      setListing(null);
      setSelected(new Set());
    }
  }, [open]);

  const probe = useMutation({
    // 起点**当参数传**,不从 state 读:setState 是异步的,翻页时读到的会是上一次的值 ——
    // 表现为"点了下一批还停在原地"。
    mutationFn: (from: number = 1) => probeUrl(workspace.id, url.trim(), optionalValue(profileId), from),
    onSuccess: (result) => {
      setListing(result);
      // 单条视频就是用户想要的那一条,直接勾上 —— 让他为一条结果再点一次是纯仪式。
      // 播放列表则一个都不勾:几百条默认全选,一次误点就是几十 GB。
      setSelected(new Set(result.is_playlist ? [] : result.entries.map((entry) => entry.url)));
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const start = useMutation({
    mutationFn: () =>
      importFromUrl({
        workspace_id: workspace.id,
        project_id: projectId ?? null,
        kind,
        max_height: maxHeight,
        profile_id: optionalValue(profileId),
        section_start: section?.start ?? null,
        section_end: section && Number.isFinite(section.end) ? section.end : null,
        items: (listing?.entries ?? [])
          .filter((entry) => selected.has(entry.url))
          .map((entry) => ({ url: entry.url, title: entry.title })),
      }),
    onSuccess: () => {
      onOpenChange(false);
      toast.success(t("urlImportQueued").replace("{n}", String(selected.size)));
      onQueued?.();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const entries = listing?.entries ?? [];
  const bestKnown = knownBestHeight(entries);
  const single = entries.length === 1 && !listing?.is_playlist;
  const section = single ? toSection(sectionStart, sectionEnd) : null;
  const allSelected = entries.length > 0 && entries.every((entry) => selected.has(entry.url));
  const toggleAll = () =>
    setSelected(allSelected ? new Set() : new Set(entries.map((entry) => entry.url)));

  return (
    <ModalShell
      open={open}
      onOpenChange={onOpenChange}
      title={t("urlImportTitle")}
      className="w-[min(560px,92vw)] max-w-none"
    >
      <div className="grid min-w-0 gap-2.5">
        <form
          className="flex min-w-0 items-center gap-1.5"
          onSubmit={(event) => {
            event.preventDefault();
            if (url.trim()) {
              setPageStart(1); // 换链接就从头开始,而不是接着上一条的页码
              probe.mutate(1);
            }
          }}
        >
          <Input
            className="min-w-0 flex-1"
            value={url}
            placeholder={t("urlImportPlaceholder")}
            onChange={(event) => setUrl(event.target.value)}
            autoFocus
          />
          <Button
            type="submit"
            size="sm"
            variant="outline"
            className="shrink-0"
            loading={probe.isPending}
            disabled={!url.trim()}
          >
            {t("urlImportProbe")}
          </Button>
        </form>

        {(profiles.data ?? []).length > 0 && (
          <label className="grid gap-1 text-xs text-muted-foreground">
            <span>{t("urlImportProfile")}</span>
            <Select value={profileId} onValueChange={setProfileId}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {/* 「不用」排第一:绝大多数链接是公开内容,借登录态既没必要也多一次占用。 */}
                <SelectItem value={NONE}>{t("urlImportProfileNone")}</SelectItem>
                {(profiles.data ?? [])
                  .filter((profile) => profile.enabled)
                  .map((profile) => (
                    <SelectItem key={profile.id} value={profile.id}>
                      {profile.name}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </label>
        )}

        {probe.isPending && (
          <p className="m-0 flex items-center gap-1.5 text-ui-xs text-muted-foreground">
            <Loader2 size={12} className="animate-openstudio-spin" /> {t("urlImportProbing")}
          </p>
        )}

        {listing && (
          <>
            <div className="flex min-w-0 items-center justify-between gap-2">
              <span className="min-w-0 flex-1 truncate text-ui-sm font-semibold text-foreground">
                {listing.title || t("urlImportUntitled")}
              </span>
              <span className="shrink-0 text-ui-xs text-muted-foreground">
                {t("urlImportCount").replace("{n}", String(entries.length))}
              </span>
            </div>
            {(listing.truncated || (listing.start ?? 1) > 1) && (
              // 截断必须说出来 —— 否则用户以为这就是全部,勾完发现少了一半。
              // 而且要给得出「往后翻」的出口:第 201 条之后并非取不到,只是要再问一次。
              <div className="flex min-w-0 flex-wrap items-center justify-between gap-1.5">
                <span className="min-w-0 flex-1 text-ui-2xs leading-[1.5] text-muted-foreground">
                  {t("urlImportRange")
                    .replace("{from}", String(listing.start ?? 1))
                    .replace("{to}", String((listing.start ?? 1) + entries.length - 1))}
                </span>
                <span className="flex shrink-0 gap-1">
                  {(listing.start ?? 1) > 1 && (
                    <Button
                      size="sm"
                      variant="outline"
                      loading={probe.isPending}
                      onClick={() => {
                        const previous = Math.max(1, (listing.start ?? 1) - 200);
                        setPageStart(previous);
                        probe.mutate(previous);
                      }}
                    >
                      {t("urlImportPrevPage")}
                    </Button>
                  )}
                  {listing.truncated && (
                    <Button
                      size="sm"
                      variant="outline"
                      loading={probe.isPending}
                      onClick={() => {
                        const next = (listing.start ?? 1) + 200;
                        setPageStart(next);
                        probe.mutate(next);
                      }}
                    >
                      {t("urlImportNextPage")}
                    </Button>
                  )}
                </span>
              </div>
            )}

            <div className="grid max-h-[38vh] min-w-0 gap-px overflow-y-auto overflow-x-hidden">
              {entries.map((entry) => {
                const checked = selected.has(entry.url);
                return (
                  <button
                    key={entry.url}
                    type="button"
                    className={cn(
                      "grid w-full cursor-pointer grid-cols-[16px_minmax(0,1fr)_auto] items-center gap-2 rounded-md border-0 bg-transparent px-1.5 py-1.5 text-left hover:bg-muted",
                      checked && "bg-accent hover:bg-accent",
                    )}
                    onClick={() =>
                      setSelected((current) => {
                        const next = new Set(current);
                        if (next.has(entry.url)) next.delete(entry.url);
                        else next.add(entry.url);
                        return next;
                      })
                    }
                    aria-pressed={checked}
                  >
                    <Checkbox checked={checked} tabIndex={-1} aria-hidden className="pointer-events-none" />
                    <span className="grid min-w-0 gap-px">
                      <span className="truncate text-ui-xs text-foreground">{entry.title}</span>
                      {entry.uploader && (
                        <span className="truncate text-ui-2xs text-muted-foreground">{entry.uploader}</span>
                      )}
                    </span>
                    <span className="timecode text-ui-2xs text-muted-foreground">
                      {entry.duration ? formatTimecode(entry.duration) : ""}
                    </span>
                  </button>
                );
              })}
            </div>

            <label className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>{t("urlImportSelectAll").replace("{n}", String(entries.length))}</span>
              <Switch checked={allSelected} onCheckedChange={toggleAll} />
            </label>

            {kind === "video" && (
              <label className="grid gap-1 text-xs text-muted-foreground">
                <span>{t("urlImportQuality")}</span>
                <Select value={String(maxHeight)} onValueChange={(next) => setMaxHeight(Number(next))}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {qualityOptions(entries.flatMap((entry) => entry.heights ?? [])).map((height) => (
                      <SelectItem key={height} value={String(height)}>
                        {height === 0 ? t("urlImportQualityBest") : `${height}p`}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {bestKnown > 0 && (
                  // 站点实际能给多少,要说出来 —— 不带登录态的 YouTube 现在只给到 360p,
                  // 而用户会以为是这个功能不行。
                  <span className="text-ui-2xs leading-[1.5] text-muted-foreground">
                    {t("urlImportQualityKnown").replace("{n}", String(bestKnown))}
                  </span>
                )}
              </label>
            )}

            {single && kind === "video" && (
              <label className="grid gap-1 text-xs text-muted-foreground">
                <span>{t("urlImportSection")}</span>
                <div className="flex min-w-0 items-center gap-1.5">
                  <Input
                    className="h-7 min-w-0 flex-1"
                    value={sectionStart}
                    placeholder={t("urlImportSectionFrom")}
                    onChange={(event) => setSectionStart(event.target.value)}
                  />
                  <span className="shrink-0 text-muted-foreground">–</span>
                  <Input
                    className="h-7 min-w-0 flex-1"
                    value={sectionEnd}
                    placeholder={t("urlImportSectionTo")}
                    onChange={(event) => setSectionEnd(event.target.value)}
                  />
                </div>
                <span className="text-ui-2xs leading-[1.5] text-muted-foreground">{t("urlImportSectionHint")}</span>
              </label>
            )}

            <label className="grid gap-1 text-xs text-muted-foreground">
              <span>{t("urlImportKind")}</span>
              <Select value={kind} onValueChange={(next) => setKind(next as "video" | "audio")}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="video">{t("urlImportKindVideo")}</SelectItem>
                  <SelectItem value="audio">{t("urlImportKindAudio")}</SelectItem>
                </SelectContent>
              </Select>
            </label>

            <Button size="sm" disabled={selected.size === 0} loading={start.isPending} onClick={() => start.mutate()}>
              <Link2 size={13} /> {t("urlImportStart").replace("{n}", String(selected.size))}
            </Button>
          </>
        )}
      </div>
    </ModalShell>
  );
}
