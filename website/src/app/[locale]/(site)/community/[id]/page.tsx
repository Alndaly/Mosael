import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { AlertCircle, ArrowLeft, ChevronRight, Upload } from "lucide-react";
import { Suspense } from "react";

import { DetailBody, InfoList, Section, SideCard, Steps, actionClass } from "@/components/community/detail";
import { DetailSkeleton } from "@/components/community/detail-skeleton";
import { CommentSection, ShareCommentCountProvider, ShareEngagement } from "@/components/community/share-detail";
import { ShareCanvasDialog } from "@/components/community/share-canvas";
import { SharePreview } from "@/components/community/share-preview";
import { toFlowGraph } from "@/components/community/share-preview-model";
import { cookieHeader, loadComments, loadShare, loadSharePayload, loadViewer } from "@/components/community/share-server";
import { formatBytes, formatShareDate } from "@/components/community/share-utils";
import { InitialTile } from "@/components/community/tile";
import { PageGlow } from "@/components/page-hero";
import { isLocale, localePath, type Locale } from "@/i18n/config";
import { shareKindLabel } from "@/lib/shareKind";
import { getMessages } from "@/i18n/messages";
import { CloudApiError, type CloudCommentPage, type CloudIdentity, type CloudShare } from "@/lib/cloud";
import { toPlainText } from "@/lib/inline-markdown";
import { pageMetadata } from "@/lib/seo";

type Params = Promise<{ locale: string; id: string }>;

function fallbackMessage(locale: Locale, error: unknown, fallback: string): string {
  return error instanceof CloudApiError ? error.text(locale) : fallback;
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { locale, id } = await params;
  if (!isLocale(locale)) return {};
  const t = getMessages(locale).community;
  let share: CloudShare | null = null;
  try {
    share = await loadShare(id, await cookieHeader());
  } catch {
    // 404 / 云端暂时不可用都退回通用标题,页面自己会把失败原因说清楚。
  }
  const summaryText = share?.summary?.trim() ? toPlainText(share.summary) : "";
  return pageMetadata({
    locale,
    path: `/community/${id}`,
    title: share?.title ?? t.name,
    description: summaryText || t.sharesSeoDescription,
    type: "article",
  });
}

function ShareMissing({ locale, message }: { locale: Locale; message: string }) {
  const t = getMessages(locale).community;
  return (
    <div className="relative isolate -mt-20 flex min-h-[78svh] flex-col items-start justify-center overflow-hidden px-5 pt-28 pb-24 sm:px-8">
      <div className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(circle_at_20%_20%,rgba(114,87,233,0.2),transparent_38%),radial-gradient(circle_at_80%_70%,rgba(255,139,120,0.16),transparent_35%)]" />
      <div className="mx-auto w-full max-w-[88rem]">
        <p className="m-0 font-mono text-sm font-bold tracking-widest text-flame uppercase">404</p>
        <h1 className="mt-6 mb-5 font-display text-[clamp(2rem,7vw,4.5rem)] leading-none font-extrabold tracking-[-0.03em]">
          {t.notFoundTitle}
        </h1>
        <p className="mt-0 mb-3 max-w-xl text-lg text-foreground">{message}</p>
        <p className="mt-0 mb-10 max-w-xl text-sm text-muted-foreground">{t.notFoundBody}</p>
        <div className="flex flex-wrap gap-3">
          <Link href={localePath(locale, "/community")} className={actionClass(true)}>
            <ArrowLeft className="size-4" aria-hidden />
            {t.backToCommunity}
          </Link>
          <Link href={localePath(locale, "/community/upload")} className={actionClass(false)}>
            <Upload className="size-4" aria-hidden />
            {t.uploadCta}
          </Link>
        </div>
      </div>
    </div>
  );
}

function ShareLoadError({ locale, message }: { locale: Locale; message: string }) {
  const t = getMessages(locale).community;
  return (
    <div className="mx-auto grid max-w-[76rem] items-start gap-4 px-5 py-24 sm:px-8">
      {/* 这一页是「社区」下的一条内容,不是另一个叫「社区分享」的分区 */}
      <h1 className="m-0 font-display text-3xl font-bold tracking-tight">{t.name}</h1>
      <div
        role="alert"
        className="flex max-w-2xl flex-wrap items-center gap-3 rounded-2xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
      >
        <AlertCircle className="size-4 shrink-0" aria-hidden />
        <span className="min-w-0 flex-1">{message}</span>
      </div>
      <div className="flex flex-wrap gap-3">
        <Link href={localePath(locale, "/community")} className={actionClass(true)}>
          <ArrowLeft className="size-4" aria-hidden />
          {t.backToCommunity}
        </Link>
      </div>
    </div>
  );
}

/**
 * 详情页的取数 / 渲染。和列表一样放在 Suspense 里:站头站尾先出,正文随云端返回补上。
 *
 * 列表和详情都不取工程文件内容;只有「下载」按钮才 `POST /download` 把它拿出来。
 */
async function ShareDetailSection({ locale, id }: { locale: Locale; id: string }) {
  const t = getMessages(locale).community;
  const cookie = await cookieHeader();

  let share: CloudShare;
  try {
    share = await loadShare(id, cookie);
  } catch (error) {
    if (error instanceof CloudApiError && error.status === 404) {
      return <ShareMissing locale={locale} message={error.text(locale)} />;
    }
    return <ShareLoadError locale={locale} message={fallbackMessage(locale, error, t.loadFailed)} />;
  }

  const [commentsResult, viewerResult, previewResult] = await Promise.allSettled([
    loadComments(id),
    loadViewer(cookie),
    // 只有工作流 / 画布才值得取 payload:插件的 payload 是 manifest,没有坐标,不做预览。
    share.kind === "workflow" || share.kind === "board"
      ? loadSharePayload(share.id, cookie)
      : Promise.resolve(null),
  ]);
  const comments: CloudCommentPage | null = commentsResult.status === "fulfilled" ? commentsResult.value : null;
  const commentsError =
    commentsResult.status === "rejected"
      ? fallbackMessage(locale, commentsResult.reason, t.loadFailed)
      : "";
  const viewer: CloudIdentity | null = viewerResult.status === "fulfilled" ? viewerResult.value : null;
  // 取失败 / 200 但不是预期形状都只是「没有预览」,页面其余部分照常,不另出错误块。
  const previewPayload = previewResult.status === "fulfilled" ? previewResult.value : null;
  // 无限画布只要最小 nodes / edges:几何在服务端算(和静态 SVG 预览同一个解析 + 同一个
  // 200 上限),**不**把那份可能 2MB 的原始工程 JSON 传给 client。插件 / 取失败 → null,
  // 详情页也就不会给「在画布里看」入口。
  const flowGraph = toFlowGraph(share.kind, previewPayload);

  const author = share.author.display_name?.trim() || share.author.handle || "—";
  const kindLabel = shareKindLabel(share.kind, t);
  // 摘要是数据字段:走 toPlainText 再上页面 / 进 meta,别把 markdown 记号当正文露出来。
  const summaryText = share.summary?.trim() ? toPlainText(share.summary) : "";
  const avatarSeed = share.author.avatar_seed || share.author.handle || share.id;

  return (
    // 统计卡(右上)与评论区(正文)是两个 client island:评论数在这一层共享,
    // 不再用 window 自定义事件广播(见 share-detail.tsx 的 ShareCommentCountProvider)。
    <ShareCommentCountProvider initialCount={share.stats.comments}>
      <section className="relative isolate -mt-20 overflow-hidden border-b border-border bg-paper">
        <PageGlow />
        <div className="mx-auto max-w-[76rem] px-5 pt-30 pb-10 sm:px-8 sm:pt-34">
          <nav aria-label="breadcrumb" className="flex flex-wrap items-center gap-1 text-sm text-muted-foreground">
            <Link href={localePath(locale, "/community")} className="hover:text-foreground">
              {t.name}
            </Link>
            {/* 没有中间的「分享」一级:社区就是插件和工作流,那一条内容不是另一种"分享" */}
            <ChevronRight className="size-3.5" aria-hidden />
            <span aria-current="page" className="truncate text-foreground">
              {share.title}
            </span>
          </nav>
          <div className="mt-8 flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between lg:gap-10">
            <div className="flex min-w-0 flex-1 items-start gap-4 sm:gap-5">
              <InitialTile seed={avatarSeed} name={author} size="lg" />
              <div className="grid min-w-0 gap-2">
                <h1 className="m-0 font-display text-3xl font-bold tracking-[-0.03em] text-balance sm:text-4xl">
                  {share.title}
                </h1>
                <p className="m-0 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm text-muted-foreground">
                  {share.author.handle ? (
                    <Link
                      href={localePath(locale, `/users/${share.author.handle}`)}
                      className="inline-flex min-w-0 items-baseline gap-x-2 font-medium text-foreground hover:text-primary"
                    >
                      <span className="truncate">{author}</span>
                      <span className="font-mono text-xs">@{share.author.handle}</span>
                    </Link>
                  ) : (
                    <span className="font-medium text-foreground">{author}</span>
                  )}
                  <span aria-hidden>·</span>
                  <span>{kindLabel}</span>
                  <span aria-hidden>·</span>
                  <time dateTime={share.created_at}>{formatShareDate(share.created_at, locale)}</time>
                </p>
                {summaryText && (
                  <p className="m-0 max-w-[46rem] text-base leading-7 text-muted-foreground">{summaryText}</p>
                )}
              </div>
            </div>
            <div className="lg:shrink-0">
              <ShareEngagement locale={locale} share={share} signedIn={viewer !== null} />
            </div>
          </div>
        </div>
      </section>

      <DetailBody
        main={
          <>
            {/* 先让人看见它长什么样,再解释它是什么。取不到 / 形状不对 / 插件都不留空框。 */}
            <div className="grid gap-3">
              {/* 首屏 / SEO 用静态 SVG;要凑近看时再开弹窗里的无限画布(它才引 xyflow)。 */}
              <SharePreview locale={locale} kind={share.kind} payload={previewPayload} />
              {flowGraph && <ShareCanvasDialog locale={locale} graph={flowGraph} />}
            </div>
            <Section id="about" title={t.whatIsTitle}>
              <p className="m-0 text-sm leading-7 text-muted-foreground">
                {share.kind === "board" ? t.whatIsBoard : share.kind === "plugin" ? t.whatIsPlugin : t.whatIsWorkflow}
              </p>
              <div className="mt-6">
                <Steps steps={t.importSteps} />
              </div>
            </Section>
            <CommentSection
              locale={locale}
              shareId={share.id}
              initial={comments}
              initialError={commentsError}
              viewer={viewer}
            />
          </>
        }
        aside={
          <>
            <SideCard title={t.authorTitle}>
              {share.author.handle ? (
                <Link
                  href={localePath(locale, `/users/${share.author.handle}`)}
                  className="flex min-w-0 items-center gap-3 rounded-lg transition-colors hover:bg-muted/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                >
                  <InitialTile seed={avatarSeed} name={author} size="md" />
                  <div className="grid min-w-0 gap-0.5">
                    <span className="truncate text-sm font-semibold">{author}</span>
                    <span className="truncate font-mono text-xs text-muted-foreground">@{share.author.handle}</span>
                  </div>
                  <ChevronRight className="ml-auto size-4 shrink-0 text-muted-foreground" aria-hidden />
                </Link>
              ) : (
                <div className="flex min-w-0 items-center gap-3">
                  <InitialTile seed={avatarSeed} name={author} size="md" />
                  <div className="grid min-w-0 gap-0.5">
                    <span className="truncate text-sm font-semibold">{author}</span>
                  </div>
                </div>
              )}
            </SideCard>
            <SideCard title={t.fileTitle}>
              <InfoList
                rows={[
                  { label: t.type, value: kindLabel },
                  { label: t.fileSize, value: formatBytes(share.bytes) },
                  { label: t.license, value: share.license || t.noLicense },
                  {
                    label: t.publishedAt,
                    value: <time dateTime={share.created_at}>{formatShareDate(share.created_at, locale)}</time>,
                  },
                ]}
              />
            </SideCard>
          </>
        }
      />
    </ShareCommentCountProvider>
  );
}

export const dynamic = "force-dynamic";

export default async function CommunitySharePage({ params }: { params: Params }) {
  const { locale, id } = await params;
  if (!isLocale(locale)) notFound();
  return (
    <Suspense fallback={<DetailSkeleton />}>
      <ShareDetailSection locale={locale} id={id} />
    </Suspense>
  );
}
