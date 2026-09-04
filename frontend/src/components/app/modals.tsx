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
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
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

/**
 * 全站弹窗的外壳:**三段** —— 钉住的头、能滚的身体、钉住的尾。
 *
 * 此前是「一整块 p-5,内容自己想办法」,于是每个内容长一点的弹窗都要在**自己内部**再套一层
 * `overflow-y-auto`。那一层带来两个后果:标题跟着内容滚走(长列表滚到一半就不知道这是什么
 * 弹窗了),以及**贴着滚动容器边缘的控件,焦点框会被裁掉** —— outline 画在 border box 外面,
 * 而那正好在容器的裁剪线之外(插件市场的搜索框和「从链接安装」按钮就是这么半截的)。
 *
 * 三段之后,滚动只发生在中间那一段,头尾各自有内边距,谁都不贴着裁剪线。中段必须同时有
 * 上下 padding:输入框的 focus ring 会画到 border box 外,若第一项紧贴 overflow 顶边,蓝色顶边仍会被裁掉。
 *
 * `sticky` 段里的 `bg-popover` 不能省:滚上来的内容会从它背后穿过去。
 */
export function ModalShell({
  open,
  onOpenChange,
  title,
  header,
  footer,
  children,
  className,
  bodyClassName,
  dismissible = true,
  modal = true,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: React.ReactNode;
  /** 钉在标题下面、**不跟着滚**的一条:搜索框、筛选器这类"作用于下面整份列表"的东西。 */
  header?: React.ReactNode;
  /** 钉在底部的动作区。表单的「取消 / 确定」放这里,长表单滚动时它仍然在。 */
  footer?: React.ReactNode;
  children: React.ReactNode;
  /** Override the default width (w-[360px]) for wider dialogs, e.g. the recorder. */
  className?: string;
  /** 覆盖滚动区的内边距 —— 内容自己就是通栏的(比如一张图)时用。 */
  bodyClassName?: string;
  /** Non-dismissible panels stay open until their own primary action completes. */
  dismissible?: boolean;
  /** Non-modal panels leave the rest of the application interactive and omit the overlay. */
  modal?: boolean;
}) {
  useUnlockBodyOnClose(open);
  return (
    <Dialog open={open} onOpenChange={onOpenChange} modal={modal}>
      <DialogContent
        showClose={dismissible}
        showOverlay={modal}
        onEscapeKeyDown={(event) => {
          if (!dismissible) event.preventDefault();
        }}
        onPointerDownOutside={(event) => {
          if (!dismissible) event.preventDefault();
        }}
        className={cn(
          "flex min-w-0 max-h-[90vh] flex-col gap-0 overflow-hidden bg-transparent p-0 backdrop-blur-xl",
          className,
        )}
      >
        <DialogHeader
          data-slot="modal-header"
          className={cn(
            "sticky top-0 z-10 shrink-0 border-b border-border/60 bg-popover/90 px-5 pb-3.5 pt-5 backdrop-blur-xl",
            header && "gap-2.5",
          )}
        >
          <DialogTitle>{title}</DialogTitle>
          {header}
        </DialogHeader>
        <div
          data-slot="modal-body"
          className={cn(
            "min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain bg-popover/90 px-5 py-5 backdrop-blur-xl [scrollbar-gutter:stable]",
            bodyClassName,
          )}
        >
          {children}
        </div>
        {footer && (
          <DialogFooter
            data-slot="modal-footer"
            className="sticky bottom-0 z-10 shrink-0 gap-2 border-t border-border/60 bg-popover/90 px-5 py-3.5 backdrop-blur-xl sm:items-center"
          >
            {footer}
          </DialogFooter>
        )}
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
  const formId = React.useId();
  const form = useForm<{ value: string }>({
    resolver: zodResolver(z.object({ value: z.string().trim().min(1, t("fieldRequired")) })),
    defaultValues: { value: initialValue },
  });
  React.useEffect(() => {
    if (open) form.reset({ value: initialValue });
  }, [open, initialValue]);
  const submit = form.handleSubmit((values) => onSubmit(values.value.trim()));

  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => !next && onCancel()}
      title={title}
      footer={
        <>
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
            {t("cancel")}
          </Button>
          <Button type="submit" form={formId} size="sm">
            {t("confirm")}
          </Button>
        </>
      }
    >
      <Form {...form}>
        <form id={formId} className="grid gap-3" onSubmit={submit} noValidate>
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
        <AlertDialogFooter className="gap-1.5">
          {/* 与任务详情等浮层统一:size=sm 的胶囊按钮,右下角对齐;确认沿用 destructive 红以示危险。 */}
          <AlertDialogCancel className="h-8 rounded-full px-3 text-xs">
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
