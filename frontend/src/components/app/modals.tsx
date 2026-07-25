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
        <AlertDialogFooter>
          <AlertDialogCancel className="h-7 rounded-md px-2 text-xs">
            {t("cancel")}
          </AlertDialogCancel>
          <AlertDialogAction
            className="h-7 rounded-md bg-destructive px-2 text-xs text-white hover:bg-destructive/90"
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
