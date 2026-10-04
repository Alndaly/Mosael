import React from "react";
import { Sparkles } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Switch } from "@/components/ui/switch";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import {
  FILLER_CATEGORIES,
  type FillerCategoryId,
  type FillerMatch,
} from "@/domain/timeline/transcriptProjection";
import { PILL } from "@/features/editor/pill";

//: 预览里最多列几处。再多也读不完,够用来判断「这一类是不是真的口癖」就行。
const PREVIEW_LIMIT = 30;

/**
 * 「口癖」:选中之前先给看。按类别开关,每类说有几处;下面列出将被选中的那些,带前后文。
 * 歧义词(中文「那个」、英文 like)默认关 —— 「那个人」「I like it」里它们是正经词(见 FILLER_CATEGORIES)。
 */
export function FillerPicker({
  matches,
  enabled,
  onEnabledChange,
  onSelect,
}: {
  matches: readonly FillerMatch[];
  enabled: ReadonlySet<FillerCategoryId>;
  onEnabledChange: (next: Set<FillerCategoryId>) => void;
  onSelect: (matches: FillerMatch[]) => void;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const chosen = matches.filter((match) => enabled.has(match.category));
  const counts = new Map<FillerCategoryId, number>();
  for (const match of matches) counts.set(match.category, (counts.get(match.category) ?? 0) + 1);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Hint label={t("fillersHint")} disabledReason={matches.length === 0 ? t("fillersNone") : undefined}>
        <PopoverTrigger asChild>
          <button type="button" className={PILL} disabled={matches.length === 0}>
            <Sparkles size={12} /> {t("fillers")}
            {chosen.length > 0 && <em>{chosen.length}</em>}
          </button>
        </PopoverTrigger>
      </Hint>
      <PopoverContent className="flex w-[300px] flex-col gap-2 p-2.5 [&>strong]:text-ui-sm" align="start">
        <strong>{t("fillers")}</strong>
        {FILLER_CATEGORIES.filter((category) => (counts.get(category.id) ?? 0) > 0).map((category) => (
          <label key={category.id} className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span className="min-w-0">
              {t(`fillerCategory_${category.id}` as never)}
              <span className="ml-1 tabular-nums">· {counts.get(category.id)}</span>
              {category.ambiguous && <span className="block text-ui-2xs">{t("fillerAmbiguousNote")}</span>}
            </span>
            <Switch
              checked={enabled.has(category.id)}
              aria-label={t(`fillerCategory_${category.id}` as never)}
              onCheckedChange={(on) => {
                const next = new Set(enabled);
                if (on) next.add(category.id);
                else next.delete(category.id);
                onEnabledChange(next);
              }}
            />
          </label>
        ))}
        <ul aria-label={t("fillerPreview")} className="m-0 grid max-h-48 list-none gap-1 overflow-y-auto p-0 text-ui-xs">
          {chosen.slice(0, PREVIEW_LIMIT).map((match) => (
            <Truncate as="li" key={match.key} className="text-muted-foreground">
              …{match.before}
              <mark className="rounded-[2px] bg-[color-mix(in_oklab,#eab308_30%,transparent)] px-0.5 text-foreground">{match.word}</mark>
              {match.after}…
            </Truncate>
          ))}
          {chosen.length > PREVIEW_LIMIT && (
            <li className="text-muted-foreground">{t("fillerPreviewMore").replace("{n}", String(chosen.length - PREVIEW_LIMIT))}</li>
          )}
        </ul>
        <Button
          size="sm"
          disabled={chosen.length === 0}
          onClick={() => {
            onSelect(chosen);
            setOpen(false);
          }}
        >
          <Sparkles size={13} /> {t("fillerSelect").replace("{n}", String(chosen.length))}
        </Button>
      </PopoverContent>
    </Popover>
  );
}
