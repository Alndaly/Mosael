import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/** Shared modal shell (no native dialogs per frontend rules). */
export function ModalShell({
  open,
  onOpenChange,
  title,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/30 animate-in fade-in-0" />
        <DialogPrimitive.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-50 w-[360px] -translate-x-1/2 -translate-y-1/2 rounded-lg border",
            "bg-popover p-3 shadow-[var(--shadow-raised)] animate-in fade-in-0 zoom-in-95",
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
  const [value, setValue] = React.useState(initialValue);
  React.useEffect(() => {
    if (open) setValue(initialValue);
  }, [open, initialValue]);

  return (
    <ModalShell open={open} onOpenChange={(next) => !next && onCancel()} title={title}>
      <form
        className="grid gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (value.trim()) onSubmit(value.trim());
        }}
      >
        <Input autoFocus value={value} onChange={(event) => setValue(event.target.value)} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
            {t("cancel")}
          </Button>
          <Button type="submit" size="sm" disabled={!value.trim()}>
            {t("confirm")}
          </Button>
        </div>
      </form>
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
