import * as React from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { useI18n } from "@/app/preferences";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Form, FormControl, FormField, FormItem, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";

/**
 * Radix 偶发在弹窗关闭时把 `<body>` 的 pointer-events:none 留住,整页点不动、必须刷新。
 * 常见于弹窗由 ContextMenu/DropdownMenu 触发:菜单关闭的清理与弹窗打开竞争,弹窗再关时只跑了
 * 自己那份,菜单留下的锁没人清。这里在 open→false 后兜底:若 DOM 里确无仍打开的 Radix 浮层,
 * 就把 body 的 pointer-events 复位(有其它浮层开着则不动,避免误清坏别人的模态屏蔽)。
 */
function useUnlockBodyOnClose(open: boolean): void {
  React.useEffect(() => {
    if (open) return;
    const id = window.setTimeout(() => {
      const stillOpen = document.querySelector(
        '[data-state="open"][role="dialog"], [data-state="open"][role="alertdialog"], [data-radix-menu-content][data-state="open"], [data-radix-popper-content-wrapper] [data-state="open"]',
      );
      if (!stillOpen && document.body.style.pointerEvents === "none") {
        document.body.style.pointerEvents = "";
      }
    }, 250);
    return () => window.clearTimeout(id);
  }, [open]);
}

/** Shared modal shell (no native dialogs per frontend rules). */
/**
 * 弹窗里一个「标题 + 控件 + 说明」表单字段的样式。
 *
 * 放这里共享,是因为它私有在某个页面里的时候,别的弹窗只能各自手搓一套——浏览器池那三个
 * 弹窗就是这么长歪的(label 用了 muted 且不加粗、输入框用默认尺寸),于是同一个应用里的
 * 弹窗表单看起来不像一家的。要改表单观感,改这一处。
 *
 * 用法:<label className={DIALOG_FIELD}><span>标题</span><Input …/><small>说明</small></label>
 */
export const DIALOG_FIELD =
  "grid gap-1 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-xs [&>span]:font-semibold [&>span]:text-foreground [&_small]:text-ui-xs [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded [&_input]:border [&_input]:border-border [&_input]:bg-field [&_input]:p-1.5 [&_input]:text-ui-sm [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-ui-sm [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none";

export function ModalShell({
  open,
  onOpenChange,
  title,
  children,
  className,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: React.ReactNode;
  /** Override the default width (w-[360px]) for wider dialogs, e.g. the recorder. */
  className?: string;
}) {
  useUnlockBodyOnClose(open);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={className}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  );
}

export function RenameDialog({
  open,
  title,
  initialValue,
  onCancel,
  onSubmit,
}: {
  open: boolean;
  title: string;
  initialValue: string;
  onCancel: () => void;
  onSubmit: (value: string) => void;
}) {
  const t = useI18n();
  const form = useForm<{ value: string }>({
    resolver: zodResolver(z.object({ value: z.string().trim().min(1, t("fieldRequired")) })),
    defaultValues: { value: initialValue },
  });
  React.useEffect(() => {
    if (open) form.reset({ value: initialValue });
  }, [open, initialValue]);
  const submit = form.handleSubmit((values) => onSubmit(values.value.trim()));

  return (
    <ModalShell open={open} onOpenChange={(next) => !next && onCancel()} title={title}>
      <Form {...form}>
        <form className="grid gap-3" onSubmit={submit} noValidate>
          <FormField
            control={form.control}
            name="value"
            render={({ field }) => (
              <FormItem>
                <FormControl>
                  <Input autoFocus {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
              {t("cancel")}
            </Button>
            <Button type="submit" size="sm">
              {t("confirm")}
            </Button>
          </div>
        </form>
      </Form>
    </ModalShell>
  );
}

export function ConfirmDialog({
  open,
  title,
  body,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  title: string;
  body?: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const t = useI18n();
  useUnlockBodyOnClose(open);
  return (
    <AlertDialog open={open} onOpenChange={(next) => !next && onCancel()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {body ? <AlertDialogDescription>{body}</AlertDialogDescription> : null}
        </AlertDialogHeader>
        <AlertDialogFooter className="gap-1.5 space-x-0 sm:gap-1.5 sm:space-x-0">
          {/* 与任务详情等浮层统一:size=sm 的胶囊按钮,右下角对齐;确认沿用 destructive 红以示危险。 */}
          <AlertDialogCancel className="mt-0 h-8 rounded-full px-3 text-xs sm:mt-0">
            {t("cancel")}
          </AlertDialogCancel>
          <AlertDialogAction
            className="h-8 rounded-full bg-destructive px-3 text-xs text-white hover:bg-destructive/90"
            onClick={(event) => {
              event.preventDefault();
              onConfirm();
            }}
          >
            {t("confirm")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
