"use client";

/**
 * 提交工作流 / 插件,以及给已有条目发新版本。
 *
 * 选了文件先在浏览器里摊开给作者看(工作流画出节点图、插件读出清单与权限),再提交。浏览器里的
 * 判断**只是预览**:同一套校验在社区服务上跑(ADR 0026 §1),这里挡住的只是明显选错的文件。
 *
 * 请求:`POST /workflows` / `POST /plugins`(multipart:文件 + 元数据),新版本
 * `POST /{kind}s/{slug}/versions`。字段名见 appendFields。
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertTriangle, FileJson, FileArchive, ImagePlus, Shield, Upload } from "lucide-react";
import * as React from "react";

import { useRequireSession } from "@/components/community/session-provider";
import { BUTTON, Field, INPUT, Notice, Spinner, SubmitButton, TEXTAREA, errorText } from "@/components/community/ui";
import { WorkflowGraphView } from "@/components/community/workflow-graph";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { toPlainText } from "@/lib/inline-markdown";
import { ENDPOINTS } from "@/lib/community/endpoints";
import { fill, formatBytes } from "@/lib/community/format";
import { parseTags } from "@/lib/community/input";
import type { ItemKind, SubmitResult } from "@/lib/community/types";
import { hasCodeNodes, readWorkflowEnvelope, type WorkflowEnvelope } from "@/lib/community/workflow-graph";
import { inspectPluginArchive, manifestSummary, manifestText, type PluginArchive, type ZipProblem } from "@/lib/community/zip";
import { cn } from "@/lib/utils";

const MAX_WORKFLOW_BYTES = 8 * 1024 * 1024;
const MAX_COVER_BYTES = 5 * 1024 * 1024;

type Preview =
  | { kind: "workflow"; envelope: WorkflowEnvelope }
  | { kind: "plugin"; archive: PluginArchive }
  | { kind: "error"; message: string };

function zipProblemText(locale: Locale, problem: ZipProblem): string {
  const template = getMessages(locale).submit.zipProblems[problem.code];
  return fill(template, { name: "name" in problem ? problem.name : "", detail: "detail" in problem ? problem.detail : "" });
}

/** 文件选择 + 拖放区。 */
function FileDrop({
  locale,
  accept,
  file,
  onFile,
  icon: Icon,
}: {
  locale: Locale;
  accept: string;
  file: File | null;
  onFile: (file: File) => void;
  icon: typeof FileJson;
}) {
  const t = getMessages(locale).submit;
  const input = React.useRef<HTMLInputElement>(null);
  const [over, setOver] = React.useState(false);
  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setOver(false);
        const dropped = event.dataTransfer.files[0];
        if (dropped) onFile(dropped);
      }}
      className={cn(
        "flex flex-wrap items-center gap-4 rounded-2xl border border-dashed px-5 py-6 transition-colors",
        over ? "border-primary bg-brand-soft" : "border-border bg-card",
      )}
    >
      <Icon className="size-7 shrink-0 text-muted-foreground" aria-hidden />
      <div className="grid min-w-0 flex-1 gap-0.5">
        {file ? (
          <>
            <span className="truncate text-sm font-semibold">{file.name}</span>
            <span className="text-xs text-muted-foreground">{formatBytes(file.size)}</span>
          </>
        ) : (
          <span className="text-sm text-muted-foreground">{t.dropHint}</span>
        )}
      </div>
      <input
        ref={input}
        type="file"
        accept={accept}
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        onChange={(event) => {
          const chosen = event.target.files?.[0];
          if (chosen) onFile(chosen);
          event.target.value = "";
        }}
      />
      <button type="button" onClick={() => input.current?.click()} className={BUTTON.secondary}>
        <Upload className="size-4" aria-hidden />
        {file ? t.changeFile : t.chooseFile}
      </button>
    </div>
  );
}

function WorkflowPreview({ locale, envelope }: { locale: Locale; envelope: WorkflowEnvelope }) {
  const t = getMessages(locale);
  const code = hasCodeNodes(envelope.graph);
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <strong className="font-semibold">{envelope.name || "—"}</strong>
        <span className="text-muted-foreground">
          {envelope.graph.nodes.length} {t.submit.nodes} · {envelope.graph.edges.length} {t.submit.edges}
        </span>
      </div>
      {code && (
        <Notice tone="info">
          <span className="inline-flex items-center gap-1.5 font-semibold text-foreground">
            <AlertTriangle className="size-4 text-[color:var(--tile-4)]" aria-hidden />
            {t.workflows.codeWarningTitle}
          </span>
          <br />
          {t.workflows.codeWarning}
        </Notice>
      )}
      <WorkflowGraphView graph={envelope.graph} label={envelope.name} codeLabel={t.workflows.codeNode} scale={0.6} />
    </div>
  );
}

function PluginPreview({ locale, archive }: { locale: Locale; archive: PluginArchive }) {
  const t = getMessages(locale);
  const summary = archive.manifest ? manifestSummary(archive.manifest, locale) : null;
  const files = archive.entries.filter((entry) => !entry.directory);
  return (
    <div className="grid gap-4">
      {archive.problems.length > 0 && (
        <Notice tone="error">
          {t.submit.blocking}
          <ul className="m-0 mt-1 list-disc pl-5">
            {archive.problems.map((problem, index) => (
              <li key={`${problem.code}-${index}`}>{zipProblemText(locale, problem)}</li>
            ))}
          </ul>
        </Notice>
      )}
      {summary && (
        <div className="grid gap-4 rounded-2xl border border-border bg-card p-5">
          <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">{t.community.id}</dt>
            <dd className="m-0 font-mono text-xs [overflow-wrap:anywhere]">{summary.id || "—"}</dd>
            <dt className="text-muted-foreground">{t.submit.title}</dt>
            <dd className="m-0">{summary.name || "—"}</dd>
            <dt className="text-muted-foreground">{t.community.version}</dt>
            <dd className="m-0 font-mono">{summary.version || "—"}</dd>
            <dt className="text-muted-foreground">{t.community.type}</dt>
            <dd className="m-0">{summary.runtime === "mcp" ? t.plugins.kindMcp : t.plugins.kindScript}</dd>
          </dl>
          <div className="grid gap-2">
            <span className="text-sm font-medium">{t.plugins.permissionsTitle}</span>
            {summary.permissions.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {summary.permissions.map((permission) => (
                  <span key={permission} className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1 font-mono text-xs">
                    <Shield className="size-3.5 text-muted-foreground" aria-hidden />
                    {permission}
                  </span>
                ))}
              </div>
            ) : (
              <span className="text-sm text-muted-foreground">{t.plugins.noPermissions}</span>
            )}
          </div>
          {summary.tools.length > 0 && (
            <div className="grid gap-2">
              <span className="text-sm font-medium">{t.plugins.toolsTitle}</span>
              <ul className="m-0 grid list-none gap-1 p-0 text-sm">
                {summary.tools.map((tool) => (
                  <li key={tool.name} className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                    <code className="rounded bg-secondary px-1.5 py-0.5 font-mono text-xs">{tool.name}</code>
                    <span className="min-w-0 truncate text-muted-foreground">{toPlainText(tool.description)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <details className="text-sm">
            <summary className="cursor-pointer font-medium">
              {t.submit.files} · {fill(t.submit.fileCount, { count: files.length })}
            </summary>
            <ul className="m-0 mt-2 grid max-h-64 list-none gap-0.5 overflow-auto p-0 font-mono text-xs">
              {files.map((entry) => (
                <li key={entry.name} className="flex justify-between gap-4">
                  <span className="truncate">{entry.name.slice(archive.root.length) || entry.name}</span>
                  <span className="shrink-0 text-muted-foreground">{formatBytes(entry.size)}</span>
                </li>
              ))}
            </ul>
          </details>
          <details className="text-sm">
            <summary className="cursor-pointer font-medium">{t.submit.manifest}</summary>
            <pre className="mt-2 max-h-80 overflow-auto rounded-xl bg-secondary/60 p-3 font-mono text-xs leading-5">{JSON.stringify(archive.manifest, null, 2)}</pre>
          </details>
        </div>
      )}
      <p className="m-0 text-xs text-muted-foreground">{t.submit.idOwned}</p>
    </div>
  );
}

/**
 * multipart 的字段(ADR 只写了「文件 + 元数据」,名字对齐社区服务的表单):`file`、`title`、`summary`、
 * `tags`(逗号分隔的一个字段)、`cover`;新版本是 `file` 与 `changelog`。
 */
function appendFields(form: FormData, fields: Record<string, string | string[] | File | null>) {
  for (const [key, value] of Object.entries(fields)) {
    if (value === null || value === "") continue;
    if (Array.isArray(value)) for (const one of value) form.append(key, one);
    else form.append(key, value);
  }
}

export function SubmitForm({
  locale,
  kind,
  version,
}: {
  locale: Locale;
  kind: ItemKind;
  /** 给已有条目发新版本:它的 slug 与标题。 */
  version?: { slug: string; title: string };
}) {
  const t = getMessages(locale);
  const router = useRouter();
  const { status, client } = useRequireSession(locale);
  const [file, setFile] = React.useState<File | null>(null);
  const [preview, setPreview] = React.useState<Preview | null>(null);
  const [reading, setReading] = React.useState(false);
  const [title, setTitle] = React.useState("");
  const [summary, setSummary] = React.useState("");
  const [tags, setTags] = React.useState("");
  const [notes, setNotes] = React.useState("");
  const [cover, setCover] = React.useState<File | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);
  const [done, setDone] = React.useState<SubmitResult | null>(null);

  if (status !== "authenticated") {
    return (
      <p className="m-0 inline-flex items-center gap-2 text-sm text-muted-foreground">
        <Spinner />
        {t.auth.checking}
      </p>
    );
  }

  const choose = async (chosen: File) => {
    setFile(chosen);
    setError(null);
    setReading(true);
    try {
      if (kind === "workflow") {
        if (chosen.size > MAX_WORKFLOW_BYTES) {
          setPreview({ kind: "error", message: formatBytes(chosen.size) });
          return;
        }
        const read = readWorkflowEnvelope(await chosen.text());
        if (!read.ok) {
          setPreview({ kind: "error", message: t.submit.workflowProblems[read.problem] });
          return;
        }
        setPreview({ kind: "workflow", envelope: read.envelope });
        if (!version) {
          setTitle((current) => current || read.envelope.name);
          setSummary((current) => current || read.envelope.description.slice(0, 200));
        }
      } else {
        const archive = await inspectPluginArchive(await chosen.arrayBuffer());
        setPreview({ kind: "plugin", archive });
        if (!version && archive.manifest) {
          const manifest = manifestSummary(archive.manifest, locale);
          const skills = archive.manifest.skills as { description?: unknown }[] | undefined;
          setTitle((current) => current || manifest.name);
          setSummary((current) => current || toPlainText(manifestText(skills?.[0]?.description, locale)).slice(0, 200));
        }
      }
    } finally {
      setReading(false);
    }
  };

  const blocking =
    !file ||
    preview?.kind === "error" ||
    (preview?.kind === "plugin" && (preview.archive.problems.length > 0 || !preview.archive.manifest));

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!file) return setError(t.submit.needFile);
    if (!version && !title.trim()) return setError(t.submit.needTitle);
    if (!client) return;
    const form = new FormData();
    if (version) appendFields(form, { file, changelog: notes.trim() });
    else appendFields(form, { file, title: title.trim(), summary: summary.trim(), tags: parseTags(tags).join(","), cover });
    setPending(true);
    try {
      const path = version ? ENDPOINTS.items.newVersion(kind, version.slug) : ENDPOINTS.items.create(kind);
      const result = await client.fetchJson<SubmitResult>(path, { method: "POST", body: form });
      if (kind === "workflow") {
        router.push(localePath(locale, `/workflows/${result.slug}`));
      } else {
        setDone(result);
      }
    } catch (caught) {
      setError(errorText(caught, t.community.genericError, t.community.networkError));
    } finally {
      setPending(false);
    }
  };

  if (done) {
    return (
      <div className="grid gap-4">
        <Notice tone="success">{t.submit.pluginDone}</Notice>
        <div className="flex flex-wrap gap-2.5">
          <Link href={localePath(locale, "/account#submissions")} className={BUTTON.primary}>
            {t.submit.goSubmissions}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <form className="grid gap-8" onSubmit={(event) => void submit(event)} noValidate>
      <div className="grid gap-3">
        <Field label={t.submit.file}>
          <FileDrop
            locale={locale}
            accept={kind === "workflow" ? ".json,application/json" : ".zip,application/zip"}
            file={file}
            onFile={(chosen) => void choose(chosen)}
            icon={kind === "workflow" ? FileJson : FileArchive}
          />
        </Field>
        {reading && <Spinner className="text-muted-foreground" />}
      </div>

      {preview && (
        <section className="grid gap-3" aria-labelledby="submit-preview">
          <h2 id="submit-preview" className="m-0 text-base font-semibold">
            {t.submit.preview}
          </h2>
          {preview.kind === "error" && <Notice tone="error">{preview.message}</Notice>}
          {preview.kind === "workflow" && <WorkflowPreview locale={locale} envelope={preview.envelope} />}
          {preview.kind === "plugin" && <PluginPreview locale={locale} archive={preview.archive} />}
          <p className="m-0 text-xs text-muted-foreground">{t.submit.previewNote}</p>
        </section>
      )}

      {version ? (
        <Field label={t.submit.notes} htmlFor="submit-notes">
          <textarea id="submit-notes" maxLength={2000} value={notes} onChange={(event) => setNotes(event.target.value)} className={TEXTAREA} />
        </Field>
      ) : (
        <div className="grid gap-5">
          <Field label={t.submit.title} htmlFor="submit-title">
            <input id="submit-title" required maxLength={80} value={title} onChange={(event) => setTitle(event.target.value)} className={INPUT} />
          </Field>
          <Field label={t.submit.summary} htmlFor="submit-summary" hint={t.submit.summaryHint}>
            <textarea id="submit-summary" maxLength={200} value={summary} onChange={(event) => setSummary(event.target.value)} className={cn(TEXTAREA, "min-h-20")} />
          </Field>
          <Field label={t.submit.tags} htmlFor="submit-tags" hint={t.submit.tagsHint}>
            <input id="submit-tags" value={tags} onChange={(event) => setTags(event.target.value)} className={INPUT} />
          </Field>
          <Field label={t.submit.cover} htmlFor="submit-cover" hint={cover ? `${cover.name} · ${formatBytes(cover.size)}` : undefined}>
            <label className={cn(BUTTON.secondary, "w-fit cursor-pointer")}>
              <ImagePlus className="size-4" aria-hidden />
              {t.submit.chooseFile}
              <input
                id="submit-cover"
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="sr-only"
                onChange={(event) => {
                  const chosen = event.target.files?.[0] ?? null;
                  setCover(chosen && chosen.size <= MAX_COVER_BYTES ? chosen : null);
                }}
              />
            </label>
          </Field>
        </div>
      )}

      {error && <Notice tone="error">{error}</Notice>}
      <div className="flex flex-wrap items-center gap-3">
        <SubmitButton pending={pending} pendingLabel={t.submit.submitting} disabled={blocking}>
          {t.submit.submit}
        </SubmitButton>
      </div>
    </form>
  );
}
