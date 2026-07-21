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
    if (target?.closest("[data-mibu-select-content]")) {
      event.preventDefault();
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent onInteractOutside={ignoreSelectOutsideInteraction} className={className}>
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
