import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Form, FormControl, FormField, FormItem, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

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
  const ignoreSelectOutsideInteraction = (event: Event) => {
    const target = event.target as HTMLElement | null;
    if (
      document.documentElement.hasAttribute("data-mibu-select-open") ||
      target?.closest("[data-mibu-select-content]")
    ) {
      event.preventDefault();
    }
  };

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-[100] bg-black/30 animate-in fade-in-0" />
        <DialogPrimitive.Content
          onInteractOutside={ignoreSelectOutsideInteraction}
          className={cn(
            "fixed left-1/2 top-1/2 z-[110] w-[360px] max-w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 rounded-lg border",
            "bg-popover p-3 shadow-[var(--shadow-raised)] animate-in fade-in-0 zoom-in-95",
            className,
          )}
        >
          <DialogPrimitive.Title className="mb-3 text-[14px] font-semibold">{title}</DialogPrimitive.Title>
          {children}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
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
  return (
    <ModalShell open={open} onOpenChange={(next) => !next && onCancel()} title={title}>
      {body && <p className="mb-3 text-[13px] text-muted-foreground">{body}</p>}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          {t("cancel")}
        </Button>
        <Button variant="destructive" size="sm" onClick={onConfirm}>
          {t("confirm")}
        </Button>
      </div>
    </ModalShell>
  );
}
