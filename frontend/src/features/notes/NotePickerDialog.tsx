import React from "react";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, FileText } from "lucide-react";
import { getNote, listNotes, type Note } from "@/api/domains/notes";
import { useI18n, usePreferences } from "@/app/preferences";
import { PickListDialog } from "@/components/app/PickListDialog";
import { Button } from "@/components/ui/button";
import { noteSnippet } from "@/features/notes/noteSnippet";
import { relativeTime } from "@/lib/time";

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
  const { locale } = usePreferences();
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
    <PickListDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("documentPick")}
      description={t("documentPickHint")}
      searchLabel={t("documentSearch")}
      query={search}
      onQueryChange={setSearch}
      items={notes.data ?? []}
      itemKey={(note) => note.id}
      row={(note) => ({
        lead: <FileText size={16} />,
        title: note.title || t("documentUntitled"),
        subtitle: noteSnippet(note.markdown),
        //: 版本号是挑了之后钉住的那一版(引用的是这一版的正文);时间说「多久前改过」,和列表、评论一个说法。
        meta: `v${note.revision} · ${relativeTime(note.updated_at, locale)}`,
      })}
      onPick={(note) => {
        onPick(note);
        onOpenChange(false);
      }}
      pending={notes.isPending}
      error={notes.isError ? notes.error.message : null}
      onRetry={() => void notes.refetch()}
      empty={{ icon: <BookOpen size={24} strokeWidth={1.5} />, text: t("documentNoMatches") }}
      notice={(notes.data?.length ?? 0) >= 200 ? t("documentRefineSearch") : undefined}
    />
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
