import * as React from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { useI18n } from "@/app/preferences";
import {
  AlertDialog,
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
 * Radix 偶发把 `<body>` 的 pointer-events:none 留住,整页点不动、必须刷新。
 *
 * 兜底**已经搬到全局**(`lib/bodyPointerLock`,挂在 App 根上)。原来这里有一份只盯自己
 * open→false 的局部版本,它漏掉的恰恰是最常见的两种:浮层**还开着就被整块卸载**(无限画布上
 * 点一下空白处就是这样,此时 open 自始至终是 true),以及关掉之后 250ms 内就卸载(它的清理
 * 函数把那次检查取消了)。而且留下锁的那个浮层常常根本不是 ModalShell —— Select、右键菜单、
 * 图片预览都能上锁,它们谁都不认识 ModalShell。
 *
 * 所以这里不再各自兜:盯住锁本身的那一份对所有来源都成立。
 */

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
  "grid gap-2 [&>span]:flex [&>span]:items-center [&>span]:gap-[3px] [&>span]:text-ui-sm [&>span]:font-medium [&>span]:text-foreground [&_small]:text-ui-xs [&_small]:leading-[1.4] [&_small]:text-muted-foreground [&_input]:resize-y [&_input]:rounded-md [&_input]:border [&_input]:border-field-border [&_input]:bg-field [&_input]:px-3 [&_input]:py-2 [&_input]:text-ui-sm [&_input]:text-foreground [&_input:focus-visible]:border-primary [&_input:focus-visible]:outline-none [&_textarea]:resize-y [&_textarea]:rounded-md [&_textarea]:border [&_textarea]:border-field-border [&_textarea]:bg-field [&_textarea]:px-3 [&_textarea]:py-2 [&_textarea]:text-ui-sm [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none";

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
 * 头尾在滚动区之外，不会被正文穿过；各段保持透明，共享外壳的一层磨砂背景。
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
          "flex min-w-0 max-h-[90vh] flex-col gap-0 overflow-hidden p-0",
          className,
        )}
      >
        <DialogHeader
          data-slot="modal-header"
          className={cn(
            // **头尾和正文之间的留白长在头尾上,不长在正文上。** 此前是头部 pb-0 + 正文 py-6:
            // 静止时看着一样,可正文一滚,那 24px 就跟着滚走了 —— 列表直接顶到搜索框下沿,
            // 像是被搜索框压住。正文只留 pt-1 / pb-1,给首尾那个输入框的聚焦光圈(ring-2)不被裁掉。
            "sticky top-0 z-10 shrink-0 px-6 pb-5 pt-6",
            header && "gap-2.5",
          )}
        >
          <DialogTitle>{title}</DialogTitle>
          {header}
        </DialogHeader>
        <div
          data-slot="modal-body"
          className={cn(
            "min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain px-6 pt-1 [scrollbar-gutter:stable]",
            footer ? "pb-1" : "pb-6",
            bodyClassName,
          )}
        >
          {children}
        </div>
        {footer && (
          <DialogFooter
            data-slot="modal-footer"
            className="sticky bottom-0 z-10 shrink-0 gap-2 px-6 pb-6 pt-5 sm:items-center"
          >
            {footer}
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}

/**
 * 填一个名字(重命名、新建)。和 ConfirmDialog 一样,**`pending` 必填**:提交后要等服务端,
 * 这期间确认键转圈、按不动、弹窗关不掉 —— 否则用户只能看着一个静止的弹窗猜有没有提交上。
 */
export function RenameDialog({
  open,
  title,
  initialValue,
  pending,
  confirmLabel,
  onCancel,
  onSubmit,
}: {
  open: boolean;
  title: string;
  initialValue: string;
  pending: boolean;
  /** 确认键上写什么;不给就是「确认」(新建时写「创建」)。 */
  confirmLabel?: string;
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
      onOpenChange={(next) => !next && !pending && onCancel()}
      title={title}
      footer={
        <>
          <Button type="button" variant="outline" disabled={pending} onClick={onCancel}>
            {t("cancel")}
          </Button>
          <Button type="submit" form={formId} loading={pending}>
            {confirmLabel ?? t("confirm")}
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

/**
 * 二次确认。**`pending` 是必填的** —— 确认之后要等一阵的动作(删除一批、卸载、移除成员)
 * 在完成前必须看得出「正在做」:确认键转圈,两个键都按不动,弹窗也关不掉。此前确认后没有任何
 * 反馈,用户只能盯着一个静止的弹窗猜是不是没点上,再点一次就是再删一次。
 *
 * 必填而不是可选:可选的话,新加的确认弹窗照样会漏,而漏的表现正是上面那种「没反应」。
 * 确认后立刻就结束的(纯本地操作)显式传 `pending={false}`。漏传是类型错误 —— 类型检查就是那道闸。
 */
export function ConfirmDialog({
  open,
  title,
  body,
  pending,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  title: string;
  body?: string;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const t = useI18n();
  return (
    <AlertDialog open={open} onOpenChange={(next) => !next && !pending && onCancel()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {body ? <AlertDialogDescription>{body}</AlertDialogDescription> : null}
        </AlertDialogHeader>
        <AlertDialogFooter>
          {/* Confirm and cancel share the same control scale as form dialogs. */}
          <AlertDialogCancel disabled={pending}>
            {t("cancel")}
          </AlertDialogCancel>
          {/* 用 Button 而不是 AlertDialogAction:后者一点就关,而这里要等动作做完。 */}
          <Button
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            loading={pending}
            onClick={onConfirm}
          >
            {t("confirm")}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
