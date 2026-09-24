import React from "react";
import {
  CheckSquare,
  Pencil,
  ArrowUpRight,
  Trash2,
  X,
} from "lucide-react";
import type { SceneSummary } from "@/api/domains/scenes";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ModalShell, ConfirmDialog } from "@/components/app/modals";
import {
  ContextMenu,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
} from "@/components/ui/context-menu";
import { ActionMenu } from "@/components/layout/ActionMenu";
import { ScenePreview } from "./ScenePreview";
import { CARD_GRID } from "@/components/layout/StudioPage";
import { SelectionCheck } from "@/components/app/SelectionCheck";
import { cn } from "@/lib/utils";
import { useI18n } from "@/app/preferences";

export function SceneList({
  scenes,
  selecting,
  onSelecting,
  onOpen,
  onRename,
  onDelete,
}: {
  scenes: SceneSummary[];
  selecting: boolean;
  onSelecting: (value: boolean) => void;
  onOpen: (id: string) => void;
  onRename: (scene: SceneSummary, name: string) => Promise<boolean>;
  onDelete: (scenes: SceneSummary[]) => Promise<string[]>;
}) {
  const t = useI18n();
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const anchor = React.useRef<string | null>(null);
  const [context, setContext] = React.useState<string[]>([]);
  const [remove, setRemove] = React.useState<SceneSummary[]>([]);
  const [rename, setRename] = React.useState<SceneSummary | null>(null);
  const [name, setName] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const ids = scenes.map((s) => s.id);
  const visibleKey = ids.join(",");
  React.useEffect(() => {
    setSelected((old) => new Set([...old].filter((id) => ids.includes(id))));
  }, [visibleKey]);
  React.useEffect(() => {
    if (!selecting) {
      setSelected(new Set());
      anchor.current = null;
    }
  }, [selecting]);
  const chosen = scenes.filter((s) => selected.has(s.id));
  const targets = scenes.filter((s) => context.includes(s.id));
  function clear() {
    setSelected(new Set());
    anchor.current = null;
    onSelecting(false);
  }
  function all() {
    onSelecting(true);
    setSelected(new Set(ids));
  }
  function toggle(id: string, shift = false) {
    onSelecting(true);
    setSelected((old) => {
      if (shift) {
        const end = ids.indexOf(id),
          start = ids.indexOf(anchor.current ?? id);
        return new Set([
          ...old,
          ...ids.slice(
            Math.min(start < 0 ? end : start, end),
            Math.max(start < 0 ? end : start, end) + 1,
          ),
        ]);
      }
      const next = new Set(old);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    if (!shift) anchor.current = id;
  }
  function edit(scene: SceneSummary) {
    setRename(scene);
    setName(scene.name);
  }
  async function confirmDelete() {
    if (busy) return;
    setBusy(true);
    try {
      const done = await onDelete(remove);
      // Failed items remain selected so they can be retried without deleting successful items twice.
      const failed = remove.filter((s) => !done.includes(s.id));
      setSelected(
        (old) =>
          new Set(
            [...old]
              .filter((id) => !done.includes(id))
              .concat(failed.map((s) => s.id)),
          ),
      );
      if (failed.length) onSelecting(true);
      setRemove([]);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div
      className={cn("scene-list", "flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto")}
      onKeyDown={(e) => {
        if (
          busy ||
          (e.target as HTMLElement).closest(
            'input:not([type="checkbox"]),textarea,[role="dialog"],[role="menu"]',
          )
        )
          return;
        if (e.key === "Escape") {
          e.preventDefault();
          clear();
        }
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "a") {
          e.preventDefault();
          all();
        }
        if ((e.key === "Delete" || e.key === "Backspace") && chosen.length) {
          e.preventDefault();
          setRemove(chosen);
        }
      }}
    >
      {selecting && (
        <div
          className="scene-selection-bar"
          role="group"
          aria-label={t("sceneListBulkBar")}
        >
          <label>
            <input
              type="checkbox"
              aria-label={t("sceneListSelectAll")}
              checked={scenes.length > 0 && chosen.length === scenes.length}
              disabled={busy}
              onChange={(e) =>
                e.target.checked ? all() : setSelected(new Set())
              }
            />
            {t("sceneListSelectedCount").replace("{n}", String(chosen.length))}
          </label>
          <div>
            <Button
              variant="outline"
              size="sm"
              disabled={busy || !chosen.length}
              onClick={() => setRemove(chosen)}
            >
              <Trash2 />
              {t("sceneListDeleteSelected")}
            </Button>
            <Button
              variant="outline"
              size="icon-sm"
              aria-label={t("sceneListClearSelection")}
              disabled={busy}
              onClick={clear}
            >
              <X />
            </Button>
          </div>
        </div>
      )}
      <ContextMenu>
        <ContextMenuTrigger asChild disabled={busy}>
          <div
            className={cn("scene-cards", CARD_GRID)}
            role="group"
            aria-label={t("sceneListLabel")}
            tabIndex={0}
            onContextMenuCapture={(e) => {
              const id = (e.target as HTMLElement).closest<HTMLElement>(
                "[data-scene-id]",
              )?.dataset.sceneId;
              setContext(
                id ? (selected.has(id) ? [...selected] : [id]) : [...selected],
              );
            }}
          >
            {scenes.map((scene) => (
              <article
                className="scene-list-card"
                key={scene.id}
                data-scene-id={scene.id}
                data-selected={selected.has(scene.id)}
              >
                <button
                  className={cn("scene-card-open", "grid w-full gap-3 rounded-lg text-left")}
                  aria-label={t("sceneListOpenNamed").replace("{name}", scene.name)}
                  aria-pressed={selecting ? selected.has(scene.id) : undefined}
                  disabled={busy}
                  onClick={(e) => {
                    if (selecting || e.metaKey || e.ctrlKey || e.shiftKey)
                      toggle(scene.id, e.shiftKey);
                    else onOpen(scene.id);
                  }}
                >
                  {/* 卡片正文排版与画板/工作流卡片逐项对齐:标题 text-ui-md、副行 muted,
                      间距一律走 gap 而不是各自的 margin。此前标题是 14px(比另外两页小一号)、
                      副行用的是前景色(比另外两页重),并排看像另一个产品里的东西。

                      右下角那个大写的对象数角标也去掉了 —— 它和副行的「N 个对象」是同一个数,
                      预览图能看见内容之后更没有必要,而另外两页的卡片上也没有这种角标。 */}
                  {/* 选中态和首页、素材页同一个样子:缩略图外一圈主色 + 右上角的勾选圈(SelectionCheck)。
                      此前是整张卡片外面套一圈描边、再铺一层底色,把标题和对象数也圈进去,
                      标题还贴着那圈边。 */}
                  {/* 圈画在缩略图**里面**(主色边框 + 内侧 1px):画在外面的话,最左、最右两列会被
                      滚动容器裁掉一截。 */}
                  <span className="relative block">
                    <ScenePreview data={scene.preview} className={selected.has(scene.id) ? "border-primary ring-1 ring-inset ring-primary" : undefined} />
                    {selecting && <SelectionCheck selected={selected.has(scene.id)} />}
                  </span>
                  <span className="truncate pr-8 text-ui-md font-semibold" title={scene.name}>{scene.name}</span>
                  <span className="text-ui-sm text-muted-foreground">
                    {t("sceneListCounts").replace("{objects}", String(scene.object_count)).replace("{shots}", String(scene.shot_count))}
                  </span>
                </button>
                {/* 选择模式下单卡的操作菜单收起来(批量动作在上面的工具条上),右上角让给勾选圈。 */}
                {!selecting && <div className="scene-card-menu">
                  <ActionMenu
                    label={t("sceneListActionsNamed").replace("{name}", scene.name)}
                    actions={[
                      {
                        label: t("sceneListOpen"),
                        icon: <ArrowUpRight />,
                        onSelect: () => onOpen(scene.id),
                        disabled: busy,
                      },
                      {
                        label: t("rename"),
                        icon: <Pencil />,
                        onSelect: () => edit(scene),
                        disabled: busy,
                      },
                      {
                        label: selected.has(scene.id) ? t("sceneListDeselect") : t("sceneListSelect"),
                        icon: <CheckSquare />,
                        onSelect: () => toggle(scene.id),
                        disabled: busy,
                      },
                      {
                        label: t("sceneListDelete"),
                        icon: <Trash2 />,
                        onSelect: () => setRemove([scene]),
                        destructive: true,
                        disabled: busy,
                      },
                    ]}
                  />
                </div>}
              </article>
            ))}
          </div>
        </ContextMenuTrigger>
        <ContextMenuContent onCloseAutoFocus={(e) => e.preventDefault()}>
          {targets.length === 1 && (
            <>
              <ContextMenuItem onSelect={() => onOpen(targets[0].id)}>
                <ArrowUpRight />
                {t("sceneListOpen")}
              </ContextMenuItem>
              <ContextMenuItem onSelect={() => edit(targets[0])}>
                <Pencil />
                {t("rename")}
              </ContextMenuItem>
              <ContextMenuSeparator />
            </>
          )}
          {targets.length === 1 && (
            <ContextMenuItem onSelect={() => toggle(targets[0].id)}>
              <CheckSquare />
              {selected.has(targets[0].id) ? t("sceneListDeselect") : t("sceneListSelect")}
            </ContextMenuItem>
          )}
          <ContextMenuItem onSelect={all}>
            <CheckSquare />
            {t("sceneListSelectAll")}
          </ContextMenuItem>
          {selecting && (
            <ContextMenuItem onSelect={clear}>
              <X />
              {t("sceneListClearSelection")}
            </ContextMenuItem>
          )}
          <ContextMenuSeparator />
          <ContextMenuItem
            disabled={!targets.length}
            className="text-destructive"
            onSelect={() => setRemove(targets)}
          >
            <Trash2 />
            {targets.length > 1 ? t("sceneListDeleteCount").replace("{n}", String(targets.length)) : t("sceneListDelete")}
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>
      <ModalShell
        open={!!rename}
        title={t("sceneRenameTitle")}
        onOpenChange={(open) => {
          if (!open && !busy) setRename(null);
        }}
        footer={
          <>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => setRename(null)}
            >
              {t("cancel")}
            </Button>
            <Button
              type="submit"
              form="scene-rename"
              loading={busy}
              disabled={!name.trim()}
            >
              {t("save")}
            </Button>
          </>
        }
      >
        <form
          id="scene-rename"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!rename || busy || !name.trim()) return;
            setBusy(true);
            try {
              if (await onRename(rename, name.trim())) setRename(null);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Input
            aria-label={t("sceneNameLabel")}
            value={name}
            maxLength={160}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
        </form>
      </ModalShell>
      <ConfirmDialog
        open={!!remove.length}
        title={
          remove.length === 1
            ? t("sceneListDeleteOneTitle").replace("{name}", remove[0].name)
            : t("sceneListDeleteManyTitle").replace("{n}", String(remove.length))
        }
        body={t("sceneListDeleteBody")}
        onCancel={() => {
          if (!busy) setRemove([]);
        }}
        pending={busy}
        onConfirm={() => void confirmDelete()}
      />
    </div>
  );
}
