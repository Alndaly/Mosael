import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDownToLine, Check, ExternalLink, Globe, Hourglass, Link2, Search, Send, Share2, ShieldAlert, Sparkles, User } from "lucide-react";
import { toast } from "sonner";

import {
  ENTITY_KINDS,
  browseCommunityAssets,
  entityKeys,
  getCommunityStatus,
  getEntityCommunity,
  importEntityFromCommunity,
  publishEntityToCommunity,
  type CommunityAsset,
  type Entity,
  type EntityCommunity,
  type EntityCommunityPublished,
  type EntityKind,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { gotoSettings } from "@/lib/deepLink";
import { cn } from "@/lib/utils";
import { COMMUNITY_STATUS_KEY, fill, openInBrowser } from "@/features/community/communityShared";
import { PublishedResult, parseTags } from "@/features/community/publishShared";
import { entityKindIcon, useCatalogLabels } from "@/features/entities/entityMeta";

/** 本机声明过的授权:真人人物只有「本人」「已获授权」能分享(「待你确认」是导入来的,还不算)。 */
function sharableConsent(entity: Entity): boolean {
  const attributes = entity.attributes as Record<string, unknown>;
  if (!attributes.real_person) return true;
  const consent = attributes.consent as { kind?: string } | undefined;
  return consent?.kind === "self" || consent?.kind === "authorized";
}

function useEntityCommunity(workspaceId: string, entityId: string) {
  return useQuery({
    queryKey: entityKeys.community(workspaceId, entityId),
    queryFn: () => getEntityCommunity(entityId),
    //: 查「社区上有没有新版本」要连一下社区;几分钟问一次足够。
    staleTime: 5 * 60_000,
  });
}

/**
 * 资产详情标题行里的「分享到社区」(ADR 0027 §4)。只给母体:分享包里带着它的变体,变体不单独发。
 * 分享过的,按钮是「发布新版本」—— 同一个链接。
 */
export function EntityShareButton({ entity, workspaceId }: { entity: Entity; workspaceId: string }) {
  const t = useI18n();
  const state = useEntityCommunity(workspaceId, entity.id);
  const [open, setOpen] = React.useState(false);
  const shared = Boolean(state.data?.published);
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)} data-entity-share="">
        <Share2 />
        {shared ? t("entityCommunityShareAgain") : t("entityCommunityShare")}
      </Button>
      <ShareEntityDialog open={open} onOpenChange={setOpen} entity={entity} workspaceId={workspaceId} state={state.data} />
    </>
  );
}

/**
 * 标题下面一条:这个资产和社区的关系 —— 发出去的那一条(已发布 / 审核中,点开看),从哪一条导入的,
 * 以及那一条在社区上出了新版本。什么关系都没有就不画。
 */
export function EntityCommunityStrip({
  entity,
  workspaceId,
  onOpen,
}: {
  entity: Entity;
  workspaceId: string;
  onOpen: (id: string) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const state = useEntityCommunity(workspaceId, entity.id);
  const published = state.data?.published ?? null;
  const source = state.data?.source ?? null;
  const latest = state.data?.latest_version ?? null;
  const newer = Boolean(source && latest && latest !== source.version);
  const again = useMutation({
    mutationFn: () => importEntityFromCommunity({ workspace_id: workspaceId, link: source?.url ?? "" }),
    onSuccess: (made) => {
      toast.success(fill(t("entitiesImported"), { name: made.name }));
      void qc.invalidateQueries({ queryKey: entityKeys.all(workspaceId) });
      onOpen(made.id);
    },
    onError: (error) => toast.error(errorText(error)),
  });
  if (!published && !source) return null;
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2 text-ui-xs" data-entity-community="">
      {published && (
        <Chip
          icon={published.status === "pending" ? <Hourglass size={12} className="text-warning" /> : <Check size={12} className="text-success" />}
          label={`${t(published.status === "pending" ? "communityStatusPending" : "communityStatusPublished")} · v${published.version}`}
          title={t("entityCommunityOpen")}
          onClick={() => openInBrowser(published.url)}
        />
      )}
      {source && (
        <Chip
          icon={<Globe size={12} />}
          label={fill(t("entityCommunityFrom"), { version: source.version })}
          title={t("entityCommunityOpen")}
          onClick={() => openInBrowser(source.url)}
        />
      )}
      {newer && (
        <span className="inline-flex items-center gap-2 rounded-full bg-warning/10 py-0.5 pl-2.5 pr-1 text-foreground" data-entity-community-newer="">
          <Sparkles size={12} className="text-warning" />
          {fill(t("entityCommunityNewVersion"), { version: latest ?? "" })}
          <Button variant="ghost" size="xs" loading={again.isPending} onClick={() => again.mutate()}>
            <ArrowDownToLine />
            {t("entityCommunityImportNew")}
          </Button>
        </span>
      )}
    </div>
  );
}

function Chip({ icon, label, title, onClick }: { icon: React.ReactNode; label: string; title: string; onClick: () => void }) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className="inline-flex cursor-pointer items-center gap-1.5 rounded-full border-0 bg-secondary px-2.5 py-1 text-muted-foreground transition-colors hover:text-foreground"
    >
      {icon}
      {label}
      <ExternalLink size={11} className="opacity-60" />
    </button>
  );
}

/**
 * 「分享到社区」弹窗:标题、简介、标签;真人人物要在这里再确认一次「已获得本人同意公开」,社区先审核。
 * 发出去之后是那一屏结果(已发布 / 审核中 + 链接)。
 */
function ShareEntityDialog({
  open,
  onOpenChange,
  entity,
  workspaceId,
  state,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  entity: Entity;
  workspaceId: string;
  state: EntityCommunity | undefined;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [title, setTitle] = React.useState(entity.name);
  const [summary, setSummary] = React.useState("");
  const [tags, setTags] = React.useState("");
  const [confirmed, setConfirmed] = React.useState(false);
  const [result, setResult] = React.useState<EntityCommunityPublished | null>(null);
  const realPerson = Boolean((entity.attributes as Record<string, unknown>).real_person);
  const republish = Boolean(state?.published);

  React.useEffect(() => {
    if (!open) return;
    setTitle(entity.name);
    setSummary(entity.description.slice(0, 300));
    setTags(entity.tags.join(", "));
    setConfirmed(false);
    setResult(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, entity.id]);

  const publish = useMutation({
    mutationFn: () =>
      publishEntityToCommunity(entity.id, {
        workspace_id: workspaceId,
        consent_confirmed: confirmed,
        title: title.trim(),
        summary: summary.trim(),
        tags: parseTags(tags),
      }),
    onSuccess: (published) => {
      setResult(published);
      void qc.invalidateQueries({ queryKey: entityKeys.community(workspaceId, entity.id) });
    },
    onError: (error: Error) => {
      toast.error(error.message);
      void qc.invalidateQueries({ queryKey: COMMUNITY_STATUS_KEY });
    },
  });

  //: 连没连看的是设置页、分享面板共用的那一份(在设置里连上就跟着变),不是资产那一格缓存里带的。
  const community = useQuery({ queryKey: COMMUNITY_STATUS_KEY, queryFn: getCommunityStatus, enabled: open });
  const status = community.data;
  const connected = status?.connected === true;
  const blocked = realPerson && !sharableConsent(entity);
  const ready = connected && !blocked && Boolean(title.trim()) && (!realPerson || confirmed);
  //: 发完之后状态刷新成「分享过」,结果那一屏的标题照发的是第几版说,不跟着跳。
  const heading = (result ? result.version !== "1" : republish) ? t("entityCommunityShareAgain") : t("entityCommunityShare");

  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => !publish.isPending && onOpenChange(next)}
      title={heading}
      className="w-[520px]"
      footer={
        result ? (
          <Button onClick={() => onOpenChange(false)}>{t("communityDone")}</Button>
        ) : connected ? (
          <>
            <Button variant="outline" disabled={publish.isPending} onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button loading={publish.isPending} disabled={!ready} onClick={() => publish.mutate()}>
              <Send /> {heading}
            </Button>
          </>
        ) : undefined
      }
    >
      {result ? (
        <PublishedResult result={result} />
      ) : !status ? (
        <Skeleton className="h-24 w-full" />
      ) : !status.configured ? (
        <p className="m-0 text-ui-sm text-muted-foreground">{t("communityNotConfiguredBody")}</p>
      ) : !connected ? (
        <div className="grid gap-3">
          <p className="m-0 text-ui-sm text-muted-foreground">{t("entityShareNeedsAccount")}</p>
          <Button
            variant="outline"
            className="w-fit"
            onClick={() => {
              onOpenChange(false);
              gotoSettings("community");
            }}
          >
            <Globe /> {t("communityGoConnect")}
          </Button>
        </div>
      ) : (
        <div className="grid gap-4" data-testid="share-entity-form">
          <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground">
            {republish ? t("entityShareAgainIntro") : t("entityShareIntro")}
          </p>
          {blocked && (
            <p role="alert" className="m-0 flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-ui-sm">
              <ShieldAlert size={15} className="mt-0.5 shrink-0 text-warning" />
              {t("entityShareNeedsConsent")}
            </p>
          )}
          <label className={DIALOG_FIELD}>
            <span>{t("communityFieldTitle")}</span>
            <Input value={title} maxLength={120} onChange={(event) => setTitle(event.currentTarget.value)} />
          </label>
          <label className={DIALOG_FIELD}>
            <span>{t("communityFieldSummary")}</span>
            <Textarea value={summary} rows={3} maxLength={300} onChange={(event) => setSummary(event.currentTarget.value)} />
          </label>
          <label className={DIALOG_FIELD}>
            <span>{t("communityFieldTags")}</span>
            <Input value={tags} placeholder={t("communityFieldTagsPlaceholder")} onChange={(event) => setTags(event.currentTarget.value)} />
          </label>
          {realPerson && !blocked && (
            <div className="grid gap-2 rounded-md border border-border px-3 py-2.5" data-share-consent="">
              <p className="m-0 text-ui-sm text-muted-foreground">{t("entityShareRealPerson")}</p>
              <label className="flex cursor-pointer items-start gap-2">
                <Checkbox className="mt-0.5" checked={confirmed} onCheckedChange={(next) => setConfirmed(next === true)} />
                <span className="grid gap-0.5">
                  <span className="text-ui-sm font-medium text-foreground">{t("entityShareConfirm")}</span>
                  <span className="text-ui-xs leading-relaxed text-muted-foreground">{t("entityShareConfirmHint")}</span>
                </span>
              </label>
            </div>
          )}
        </div>
      )}
    </ModalShell>
  );
}

/**
 * 资产库的「从社区导入」:贴一个资产页的链接,或者在社区上的列表里点一个。导入 = 下载分享包和参考图、
 * 按哈希核对、作为素材进这个工作区,建好资产和变体。**不需要连社区账号。**
 */
export function ImportFromCommunityDialog({
  open,
  onOpenChange,
  workspaceId,
  initialKind,
  onImported,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: string;
  initialKind: EntityKind;
  onImported: (entity: Entity) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const labels = useCatalogLabels();
  const [link, setLink] = React.useState("");
  const [kind, setKind] = React.useState<EntityKind>(initialKind);
  const [search, setSearch] = React.useState("");
  const [picked, setPicked] = React.useState<string | null>(null);
  const keyword = search.trim();

  React.useEffect(() => {
    if (!open) return;
    setLink("");
    setSearch("");
    setPicked(null);
    setKind(initialKind);
  }, [open, initialKind]);

  const list = useQuery({
    queryKey: ["community-assets", kind, keyword],
    queryFn: () => browseCommunityAssets({ assetKind: kind, q: keyword }),
    enabled: open,
    staleTime: 60_000,
  });
  const run = useMutation({
    mutationFn: (target: string) => importEntityFromCommunity({ workspace_id: workspaceId, link: target }),
    onSuccess: (made) => {
      toast.success(fill(t("entitiesImported"), { name: made.name }));
      void qc.invalidateQueries({ queryKey: entityKeys.all(workspaceId) });
      onImported(made);
    },
    onError: (error) => toast.error(errorText(error)),
    onSettled: () => setPicked(null),
  });
  const importOne = (target: string, slug?: string) => {
    if (run.isPending) return;
    setPicked(slug ?? null);
    run.mutate(target);
  };

  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => !run.isPending && onOpenChange(next)}
      title={t("entitiesImport")}
      className="w-[min(720px,calc(100vw-32px))] h-[min(640px,calc(100dvh-32px))]"
      header={
        <div className="grid gap-3">
          <form
            className="flex min-w-0 items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (link.trim()) importOne(link.trim());
            }}
          >
            <span className="relative min-w-0 flex-1">
              <Link2 size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input
                autoFocus
                size="sm"
                className="pl-8"
                aria-label={t("entitiesImportLink")}
                placeholder={t("entitiesImportLinkPlaceholder")}
                value={link}
                onChange={(event) => setLink(event.currentTarget.value)}
              />
            </span>
            <Button type="submit" size="sm" disabled={!link.trim()} loading={run.isPending && picked === null}>
              <ArrowDownToLine />
              {t("entitiesImportGo")}
            </Button>
          </form>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="text-ui-xs text-muted-foreground">{t("entitiesImportBrowse")}</span>
            <div role="radiogroup" aria-label={t("entitiesKinds")} className="flex gap-1">
              {ENTITY_KINDS.map((one) => (
                <button
                  key={one}
                  type="button"
                  role="radio"
                  aria-checked={kind === one}
                  onClick={() => setKind(one)}
                  className={cn(
                    "cursor-pointer rounded-full border-0 px-2.5 py-0.5 text-ui-xs transition-colors",
                    kind === one ? "bg-action text-action-foreground" : "bg-secondary text-muted-foreground hover:text-foreground",
                  )}
                >
                  {labels.kind(one)}
                </button>
              ))}
            </div>
            <span className="relative min-w-40 flex-1">
              <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input
                size="sm"
                className="pl-8"
                aria-label={t("entitiesImportSearch")}
                placeholder={t("entitiesImportSearch")}
                value={search}
                onChange={(event) => setSearch(event.currentTarget.value)}
              />
            </span>
          </div>
        </div>
      }
    >
      {list.isPending ? (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3" aria-busy="true">
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} className="aspect-[4/5] w-full rounded-lg" />
          ))}
        </div>
      ) : list.isError ? (
        <div role="alert" className="grid justify-items-center gap-2 py-10 text-center text-ui-sm text-muted-foreground">
          {list.error.message}
          <Button variant="ghost" size="sm" onClick={() => void list.refetch()}>
            {t("retry")}
          </Button>
        </div>
      ) : list.data.items.length === 0 ? (
        <p className="m-0 py-10 text-center text-ui-sm text-muted-foreground">{keyword ? t("studioNoMatches") : t("entitiesImportEmpty")}</p>
      ) : (
        <ul className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3 p-0" data-community-assets="">
          {list.data.items.map((item) => (
            <li key={item.slug} className="grid">
              <CommunityAssetTile
                item={item}
                pending={run.isPending && picked === item.slug}
                disabled={run.isPending}
                onPick={() => importOne(item.slug, item.slug)}
              />
            </li>
          ))}
        </ul>
      )}
    </ModalShell>
  );
}

function CommunityAssetTile({
  item,
  pending,
  disabled,
  onPick,
}: {
  item: CommunityAsset;
  pending: boolean;
  disabled: boolean;
  onPick: () => void;
}) {
  const t = useI18n();
  const KindIcon = entityKindIcon(item.asset_kind);
  return (
    <button
      type="button"
      disabled={disabled}
      aria-busy={pending || undefined}
      onClick={onPick}
      data-community-asset={item.slug}
      className="group grid cursor-pointer content-start gap-2 rounded-lg border-0 bg-transparent p-0 text-left disabled:cursor-default"
    >
      <span className="relative block aspect-[4/5] overflow-hidden rounded-lg border border-border bg-secondary">
        {item.cover_url ? (
          <img src={item.cover_url} alt="" loading="lazy" className="absolute inset-0 size-full object-cover transition-transform group-hover:scale-[1.02]" />
        ) : (
          <span className="absolute inset-0 grid place-items-center text-muted-foreground">
            <KindIcon size={22} />
          </span>
        )}
        {item.real_person && (
          <span className="absolute left-2 top-2 inline-flex items-center gap-1 rounded-full bg-background/85 px-2 py-0.5 text-ui-2xs font-medium backdrop-blur">
            <User size={11} />
            {t("entitiesImportRealPerson")}
          </span>
        )}
        <span
          className={cn(
            "absolute inset-x-2 bottom-2 inline-flex items-center justify-center gap-1.5 rounded-md bg-action py-1.5 text-ui-xs font-medium text-action-foreground transition-opacity",
            pending ? "opacity-100" : "opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100",
          )}
        >
          {pending ? <Hourglass size={12} /> : <ArrowDownToLine size={12} />}
          {t("entitiesImportGo")}
        </span>
      </span>
      <span className="grid min-w-0 gap-0.5 px-0.5">
        <span className="truncate text-ui-sm font-medium text-foreground">{item.title}</span>
        <span className="truncate text-ui-2xs text-muted-foreground">
          {fill(t("entitiesImportMeta"), { refs: item.reference_count, variants: item.variant_count, author: item.author_name })}
        </span>
      </span>
    </button>
  );
}
