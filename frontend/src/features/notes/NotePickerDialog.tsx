import React from "react";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Search } from "lucide-react";
import { getNote, listNotes, type Note } from "@/api/domains/notes";
import { useI18n } from "@/app/preferences";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LoadingState } from "@/components/layout/LoadingState";

export function NotePickerDialog({
  workspaceId,
  open,
  onOpenChange,
  onPick,
}: {
  workspaceId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPick: (note: Note) => void;
}) {
  const t = useI18n();
  const [search, setSearch] = React.useState("");
  const [query, setQuery] = React.useState("");
  React.useEffect(() => {
    const timer = setTimeout(() => setQuery(search), 200);
    return () => clearTimeout(timer);
  }, [search]);
  const notes = useQuery({
    queryKey: ["note-picker", workspaceId, query],
    queryFn: () => listNotes(workspaceId, query),
    enabled: open,
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[min(36rem,calc(100dvh-2rem))] max-w-xl flex-col overflow-hidden gap-4">
        <DialogHeader>
          <DialogTitle>{t("documentPick")}</DialogTitle>
          <DialogDescription>{t("documentPickHint")}</DialogDescription>
        </DialogHeader>
        <div className="relative">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            className="pl-9"
            aria-label={t("documentSearch")}
            placeholder={t("documentSearch")}
            value={search}
            maxLength={300}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          {notes.isPending ? (
            <LoadingState />
          ) : notes.isError ? (
            <div
              role="alert"
              className="m-auto text-center text-ui-sm text-muted-foreground"
            >
              {notes.error.message}
              <Button variant="ghost" onClick={() => void notes.refetch()}>
                {t("retry")}
              </Button>
            </div>
          ) : !notes.data.length ? (
            <div className="m-auto flex flex-col items-center gap-3 py-8 text-center text-muted-foreground">
              <BookOpen size={28} strokeWidth={1.5} />
              <span>{t("documentNoMatches")}</span>
            </div>
          ) : (
            notes.data.map((note) => (
              <button
                key={note.id}
                className="flex shrink-0 items-start gap-3 rounded-lg p-3 text-left transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => {
                  onPick(note);
                  onOpenChange(false);
                }}
              >
                <BookOpen size={18} className="mt-1 shrink-0 text-primary" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-ui-sm font-medium">
                    {note.title || t("documentUntitled")}
                  </span>
                  <span className="mt-1 line-clamp-2 break-words text-ui-xs text-muted-foreground">
                    {note.markdown.slice(0, 200)}
                  </span>
                  <span className="mt-2 block text-ui-2xs text-muted-foreground">
                    v{note.revision} ·{" "}
                    {new Date(note.updated_at).toLocaleDateString()}
                  </span>
                </span>
              </button>
            ))
          )}
        </div>
        {(notes.data?.length ?? 0) >= 200 && (
          <p className="text-ui-xs text-muted-foreground">
            {t("documentRefineSearch")}
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function NoteReferenceField({
  workspaceId,
  value,
  onChange,
}: {
  workspaceId: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const note = useQuery({
    queryKey: ["note", workspaceId, value],
    queryFn: () => getNote(workspaceId, value),
    enabled: !!value,
    retry: false,
  });
  return (
    <>
      <Button
        variant="outline"
        className="w-full min-w-0 justify-start"
        onClick={() => setOpen(true)}
      >
        <BookOpen size={15} className="shrink-0" />
        <span className="truncate">
          {value
            ? note.data?.title ||
              (note.isError ? t("documentUnavailable") : value)
            : t("documentPick")}
        </span>
      </Button>
      <NotePickerDialog
        workspaceId={workspaceId}
        open={open}
        onOpenChange={setOpen}
        onPick={(note) => onChange(note.id)}
      />
    </>
  );
}
