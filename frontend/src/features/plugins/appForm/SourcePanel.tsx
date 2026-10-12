import React from "react";
import { Check, Plus } from "lucide-react";

import type { WorkflowApp, WorkflowFillable } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { CatalogBadge } from "@/components/app/CatalogDialog";
import { IconButton } from "@/components/ui/icon-button";
import { SearchInput } from "@/components/ui/search-input";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { KindIcon, techText, valueText, visualOf } from "@/features/plugins/appForm/fieldFacts";
import { LocateNodeButton } from "@/features/plugins/workbench/LocateNodeButton";
import { exposable, matchesSource, shortTitle, sourceGroups, type FormDraft } from "@/features/plugins/workflowAppForm";
import { cn } from "@/lib/utils";

/**
 * 「工作流里能填的」:这张图全部能填的项,**按节点分组**(组名是节点给人看的名字 —— 用户起的标题,没起就是 ComfyUI 给这类
 * 节点的名字;节点号、类名在悬停说明里),种子 / 尺寸 / 跑几遍是「整张图」那一组。每一行:种类图标、名字、现在的值,右边一颗
 * 「+」放进表单;已经在表单上的打勾,再点一下拿掉。子图里面的节点灰着、说为什么。
 *
 * 组标题右边的 `#节点号` 是一颗按钮(和助手回复里的 `#12` 同一颗):点了在画布上定位这个节点 —— 名字是用户起的,
 * 光看名字对不上画布上哪一个(维护者提的)。「整张图」那一组没有节点,不给按钮。
 */
export function SourcePanel({
  data,
  draft,
  onAdd,
  onRemove,
}: {
  data: WorkflowApp;
  draft: FormDraft;
  onAdd: (item: WorkflowFillable) => void;
  onRemove: (key: string) => void;
}) {
  const t = useI18n();
  const [query, setQuery] = React.useState("");
  const items = data.items ?? [];
  const chosen = new Set(draft.items.map((one) => one.key));
  const groups = sourceGroups(items.filter((item) => matchesSource(item, query)));
  return (
    <section aria-label={t("workflowAppSource")} className="grid min-w-0 content-start gap-3" data-app-zone="source">
      <div className="grid gap-0.5">
        <h4 className="m-0 flex items-center gap-1.5 text-ui-sm font-semibold text-foreground">
          {t("workflowAppSource")}
          <span className="text-ui-xs font-normal tabular-nums text-muted-foreground">{items.length}</span>
        </h4>
        <p className="m-0 text-ui-xs text-muted-foreground">{t("workflowAppSourceHint")}</p>
      </div>
      <SearchInput className="block" size="sm" value={query} placeholder={t("workflowAppSearch")} aria-label={t("workflowAppSearch")}
               onChange={(event) => setQuery(event.target.value)} />
      {groups.length === 0 && query.trim() && (
        <p className="m-0 text-ui-xs text-muted-foreground">{t("workflowAppSearchEmpty").replace("{query}", query.trim())}</p>
      )}
      {groups.map((group) => {
        const name = group.node ? group.label : t("workflowAppGraphGroup");
        return (
          <div key={group.node || "graph"} className="grid min-w-0 gap-1" data-source-group={group.node}>
            {/*
              这一处只留一条说明:说的是这个节点**是什么**(节点号 · 类名),挂在标题这一条上 —— 名字和节点号都归它管。
              定位那颗按钮自己不挂说明(两处的说法不一样,一处挂两条是噪音),它的名字走 aria-label(「在画布上定位 #706」)。
            */}
            <Hint label={group.node ? t("workflowAppNodeDetail").replace("{node}", group.node).replace("{class}", group.classType || "?") : undefined}>
              <h5 className="m-0 flex min-w-0 items-baseline gap-1.5 px-1 text-ui-xs font-semibold text-muted-foreground">
                <Truncate className="min-w-0">{name}</Truncate>
                {group.node && (
                  /*
                    按钮和它失败时那句话装在一个会折行的盒子里(见 LocateNodeButton):「画布上没有节点 #706」这种话说得长,
                    让它在这一行里折到下一行,而不是把标题顶宽、挤出这一列。
                  */
                  <span className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-1.5">
                    <LocateNodeButton
                      node={group.node}
                      ariaLabel={t("workbenchAssistantLocate").replace("{node}", group.node)}
                      className="shrink-0 font-sans text-ui-xs font-normal tabular-nums text-muted-foreground hover:text-foreground"
                    />
                  </span>
                )}
              </h5>
            </Hint>
            <ul aria-label={group.node ? `${name} #${group.node}` : name} className="m-0 grid list-none gap-0.5 p-0">
              {group.items.map((item) => (
                <SourceRow key={item.key} item={item} added={chosen.has(item.key)}
                           onAdd={() => onAdd(item)} onRemove={() => onRemove(item.key)} />
              ))}
            </ul>
          </div>
        );
      })}
    </section>
  );
}

function SourceRow({ item, added, onAdd, onRemove }: {
  item: WorkflowFillable;
  added: boolean;
  onAdd: () => void;
  onRemove: () => void;
}) {
  const t = useI18n();
  const allowed = exposable(item);
  const name = shortTitle(item);
  const tech = techText(item, t);
  const main = item.kind === "text" && Boolean(item.role);
  return (
    <li data-source-item={item.key}
        className={cn("flex min-w-0 items-center gap-2 rounded-md px-1 py-1", added ? "bg-accent/40" : "hover:bg-secondary/60",
          !allowed && "opacity-60")}>
      <KindIcon visual={visualOf(item, main)} />
      <Hint label={item.hint || tech || undefined} hint={item.hint ? tech || undefined : undefined}>
        <span className="grid min-w-0 flex-1 gap-0">
          <Truncate className="text-ui-sm text-foreground">{name}</Truncate>
          <Truncate className="text-ui-2xs text-muted-foreground">{valueText(item, t)}</Truncate>
        </span>
      </Hint>
      {!item.common && <CatalogBadge tone="muted">{t("workflowAppAdvanced")}</CatalogBadge>}
      {added ? (
        <IconButton label={t("workflowAppAdded").replace("{name}", item.title)} aria-pressed className="shrink-0"
                    onClick={onRemove}>
          <Check />
        </IconButton>
      ) : (
        <IconButton label={t("workflowAppAdd").replace("{name}", item.title)} className="shrink-0 text-muted-foreground"
                    disabled={!allowed} disabledReason={t("workflowAppSubgraph")} onClick={onAdd}>
          <Plus />
        </IconButton>
      )}
    </li>
  );
}
