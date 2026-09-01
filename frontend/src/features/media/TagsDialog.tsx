import * as React from "react";
import { X } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ModalShell } from "@/components/app/modals";

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
    <ModalShell
      open={open}
      onOpenChange={(next) => !next && onCancel()}
      title={title}
      footer={
        <>
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
            {t("cancel")}
          </Button>
          <Button type="button" size="sm" onClick={() => onSubmit(commitDraft())}>
            {t("confirm")}
          </Button>
        </>
      }
    >
      {body && <p className="mb-3 text-ui-md text-muted-foreground">{body}</p>}
      <div className="grid gap-3">
        {tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {tags.map((tag) => (
              <span
                className="inline-flex items-center gap-[3px] rounded-full border border-border bg-panel px-[9px] py-px text-ui-xs text-muted-foreground transition-colors"
                key={tag}
              >
                {tag}
                <button
                  type="button"
                  aria-label={t("delete")}
                  className="ml-px grid place-items-center border-0 bg-transparent p-0 text-inherit opacity-70 hover:opacity-100"
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
            if (event.key === "Enter" && !event.nativeEvent.isComposing) {
              event.preventDefault();
              commitDraft();
            }
          }}
        />
      </div>
    </ModalShell>
  );
}
