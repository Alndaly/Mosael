"use client";

import { AlertCircle, FileJson, LoaderCircle, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { actionClass } from "@/components/community/detail";
import { IdentityForm } from "@/components/community/identity-form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { type Locale, localePath } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { CloudApiError, cloudLocale, cloudShares, type CloudIdentity, type CloudShareKind } from "@/lib/cloud";
import { invalidateAfterShareChange } from "@/lib/query-invalidation";

import { MAX_SHARE_BYTES, measurePayload, publicIdentity } from "./share-utils";

/**
 * 上传表单。
 *
 * 三件事按顺序发生:登录(服务端已在页面里拦住)、是否有昵称(没有就先起名,见 IdentityForm)、
 * 然后是表单本身。文件**先在浏览器里读成 JSON 并量紧凑字节数**,超过 2 MB 当场说清楚,
 * 不把一份注定 413 的文件发到云端再等一句报错。
 */
export function UploadForm({ locale, viewer }: { locale: Locale; viewer: CloudIdentity }) {
  const t = getMessages(locale).community;
  const router = useRouter();
  const queryClient = useQueryClient();
  const [identity, setIdentity] = React.useState<CloudIdentity | null>(viewer);
  const [needsIdentity, setNeedsIdentity] = React.useState(!viewer.display_name);
  const [kind, setKind] = React.useState<CloudShareKind>("workflow");
  const [title, setTitle] = React.useState("");
  const [summary, setSummary] = React.useState("");
  const [license, setLicense] = React.useState("");
  const [payload, setPayload] = React.useState<unknown>(null);
  const [payloadReady, setPayloadReady] = React.useState(false);
  const [fileName, setFileName] = React.useState("");
  const [fileBytes, setFileBytes] = React.useState(0);
  const [fileError, setFileError] = React.useState("");
  const [titleError, setTitleError] = React.useState("");
  const [error, setError] = React.useState("");
  const [identityNotice, setIdentityNotice] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const fileInput = React.useRef<HTMLInputElement>(null);

  const onFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    setFileName(file?.name ?? "");
    setPayload(null);
    setPayloadReady(false);
    setFileBytes(0);
    setFileError("");
    if (!file) return;
    // 明显过大的文件不必先读进内存;接近上限的仍要解析后按紧凑 JSON 精确量。
    if (file.size > MAX_SHARE_BYTES * 8) {
      setFileError(t.fileTooLarge);
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(await file.text());
    } catch {
      setFileError(t.fileInvalid);
      return;
    }
    const bytes = measurePayload(parsed);
    setFileBytes(bytes);
    if (bytes > MAX_SHARE_BYTES) {
      setFileError(t.fileTooLarge);
      return;
    }
    setPayload(parsed);
    setPayloadReady(true);
  };

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) return;
    setError("");
    setTitleError("");
    setFileError("");
    if (!payloadReady) {
      setFileError(t.fileRequired);
      return;
    }
    if (!title.trim()) {
      setTitleError(t.titleRequired);
      return;
    }
    setBusy(true);
    try {
      const { share } = await cloudShares.create({
        kind,
        // 发布时声明这一行标题 / 简介的语言:云端必填,缺了会 422。
        locale: cloudLocale(locale),
        title: title.trim(),
        summary: summary.trim() || undefined,
        license: license || undefined,
        payload,
      });
      // 上传成功:我的分享 + 概览统计 + 该 kind 的列表都多了一条(见 lib/query-invalidation.ts)。
      // 目标详情页不读这些缓存,但回到控制台 / 列表时不该还是旧的;失效即可,不必等重取。
      void invalidateAfterShareChange(queryClient, share.kind);
      // 成功就跳到详情页 —— 只弹一个 toast 的话,用户不知道自己的分享长什么样。
      router.push(localePath(locale, `/community/${share.id}`));
    } catch (failure) {
      if (failure instanceof CloudApiError) {
        if (failure.code === "identity_required") {
          setNeedsIdentity(true);
          setIdentityNotice(failure.text(locale));
        } else {
          setError(failure.text(locale));
          if (failure.code === "payload_too_large") setFileError(t.fileTooLarge);
        }
      } else {
        setError(t.uploadFailed);
      }
    } finally {
      setBusy(false);
    }
  };

  if (needsIdentity || !identity?.display_name) {
    return (
      <div className="grid gap-4 rounded-2xl border border-border bg-card p-6">
        {identityNotice && (
          <output className="block rounded-xl border border-primary/25 bg-brand-soft px-3 py-2 text-[13px] leading-5 text-primary">
            {identityNotice}
          </output>
        )}
        <IdentityForm
          locale={locale}
          initialDisplayName={identity?.display_name ?? ""}
          onDone={(updated) => {
            // 服务端回的是账号形状;只留公开三列,邮箱不跟着进客户端状态。
            const saved: CloudIdentity = publicIdentity(updated);
            setIdentity(saved);
            setNeedsIdentity(false);
          }}
        />
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="grid gap-5">
      <div className="grid gap-1.5">
        <Label htmlFor="share-kind">{t.fieldKind}</Label>
        <Select value={kind} onValueChange={(value) => setKind(value as CloudShareKind)}>
          <SelectTrigger id="share-kind" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="workflow">{t.kindWorkflow}</SelectItem>
            <SelectItem value="board">{t.kindBoard}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="share-title">{t.fieldTitle}</Label>
        <Input
          id="share-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder={t.fieldTitlePlaceholder}
          maxLength={200}
          required
          aria-invalid={Boolean(titleError)}
          aria-describedby={titleError ? "share-title-error" : undefined}
        />
        {titleError && (
          <p id="share-title-error" role="alert" className="m-0 flex items-start gap-1.5 text-[13px] text-destructive">
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            {titleError}
          </p>
        )}
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="share-summary">{t.fieldSummary}</Label>
        <Textarea
          id="share-summary"
          value={summary}
          onChange={(event) => setSummary(event.target.value)}
          placeholder={t.fieldSummaryPlaceholder}
          rows={4}
          maxLength={500}
        />
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="share-license">{t.fieldLicense}</Label>
        <Select
          value={license || "none"}
          onValueChange={(value) => setLicense(value === "none" ? "" : value)}
        >
          <SelectTrigger id="share-license" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">{t.noLicense}</SelectItem>
            {t.licenseOptions.map((option) => (
              <SelectItem key={option} value={option}>
                {option}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="grid gap-1.5">
        <span className="text-sm font-medium">{t.fieldFile}</span>
        {/*
          文件选择是**唯一**保留原生 `<input type="file">` 的地方:HTML 只能用原生文件框
          打开系统选择器,自己拼一个 div 反而会丢掉键盘、读屏和系统对话框。这里把 input
          留成透明可聚焦的原生控件,再让下面这颗按钮去 `click()` 它 —— 外观归按钮,能力归原生。
        */}
        <input
          ref={fileInput}
          type="file"
          accept=".json,application/json"
          onChange={(event) => void onFile(event)}
          className="sr-only"
          aria-label={t.chooseFile}
          aria-invalid={Boolean(fileError)}
          aria-describedby={fileError ? "share-file-error" : undefined}
        />
        <button
          type="button"
          onClick={() => fileInput.current?.click()}
          aria-describedby={fileError ? "share-file-error" : undefined}
          className="flex cursor-pointer flex-wrap items-center gap-3 rounded-xl border border-dashed border-border bg-card px-4 py-4 text-left text-sm transition-colors hover:border-primary/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          <FileJson className="size-5 shrink-0 text-primary" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="block truncate font-medium">{fileName || t.chooseFile}</span>
            <span className="block text-xs text-muted-foreground">
              {fileName && fileBytes > 0 ? `${(fileBytes / 1024).toFixed(1)} KB · ` : ""}
              {t.fileHint}
            </span>
          </span>
        </button>
        {fileError && (
          <p id="share-file-error" role="alert" className="m-0 flex items-start gap-1.5 text-[13px] text-destructive">
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            {fileError}
          </p>
        )}
      </div>

      {error && (
        <p role="alert" className="m-0 flex items-start gap-1.5 rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-[13px] leading-5 text-destructive">
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
          {error}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3 border-t border-border pt-5">
        <button type="submit" disabled={busy} className={actionClass(true)}>
          {busy ? (
            <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
          ) : (
            <Upload className="size-4" aria-hidden />
          )}
          {busy ? t.submittingUpload : t.submitUpload}
        </button>
        <p className="m-0 text-xs text-muted-foreground">{t.fileHint}</p>
      </div>
    </form>
  );
}
