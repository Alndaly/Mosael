import * as React from "react";
import { X } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ModalShell } from "@/components/ui/modals";

/** 标签编辑器:芯片列表 + 回车追加;既用于单素材编辑,也用于批量追加。 */
export function TagsDialog({
  open,
  title,
  body,
  initialTags,
  onCancel,
  onSubmit,
}: {
  open: boolean;
  title: string;
  body?: string;
  initialTags: string[];
  onCancel: () => void;
  onSubmit: (tags: string[]) => void;
}) {
  const t = useI18n();
  const [tags, setTags] = React.useState<string[]>(initialTags);
  const [draft, setDraft] = React.useState("");

  React.useEffect(() => {
    if (open) {
      setTags(initialTags);
      setDraft("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const commitDraft = (): string[] => {
    const value = draft.trim();
    setDraft("");
    if (!value || tags.includes(value)) return tags;
    const next = [...tags, value];
    setTags(next);
    return next;
  };

  return (
    <ModalShell open={open} onOpenChange={(next) => !next && onCancel()} title={title}>
      {body && <p className="mb-3 text-[13px] text-muted-foreground">{body}</p>}
      <div className="grid gap-3">
        {tags.length > 0 && (
          <div className="tag-editor-list">
            {tags.map((tag) => (
              <span className="tag-chip removable" key={tag}>
                {tag}
                <button
                  type="button"
                  aria-label={t("delete")}
                  onClick={() => setTags((current) => current.filter((item) => item !== tag))}
                >
                  <X size={10} />
                </button>
              </span>
            ))}
          </div>
        )}
        <Input
          autoFocus
          value={draft}
          placeholder={t("tagInputPlaceholder")}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commitDraft();
            }
          }}
        />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
            {t("cancel")}
          </Button>
          <Button type="button" size="sm" onClick={() => onSubmit(commitDraft())}>
            {t("confirm")}
          </Button>
        </div>
      </div>
    </ModalShell>
  );
}
