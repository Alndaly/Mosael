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
      className="scene-list"
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
          aria-label="场景批量操作"
        >
          <label>
            <input
              type="checkbox"
              aria-label="全选场景"
              checked={scenes.length > 0 && chosen.length === scenes.length}
              disabled={busy}
              onChange={(e) =>
                e.target.checked ? all() : setSelected(new Set())
              }
            />
            已选 {chosen.length} 个场景
          </label>
          <div>
            <Button
              variant="outline"
              size="sm"
              disabled={busy || !chosen.length}
              onClick={() => setRemove(chosen)}
            >
              <Trash2 />
              删除所选
            </Button>
            <Button
              variant="outline"
              size="icon-sm"
              aria-label="取消选择"
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
            className="scene-cards"
            role="group"
            aria-label="场景列表"
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
                  className="scene-card-open"
                  aria-label={`打开场景 ${scene.name}`}
                  disabled={busy}
                  onClick={(e) => {
                    if (selecting || e.metaKey || e.ctrlKey || e.shiftKey)
                      toggle(scene.id, e.shiftKey);
                    else onOpen(scene.id);
                  }}
                >
                  <div className="scene-card-art">
                    <ScenePreview data={scene.preview} />
                    <span>{String(scene.object_count).padStart(2, "0")}</span>
                  </div>
                  <h2 title={scene.name}>{scene.name}</h2>
                  <p>
                    {scene.object_count} 个对象 · {scene.shot_count} 个镜头
                  </p>
                </button>
                {selecting && (
                  <input
                    className="scene-card-check"
                    type="checkbox"
                    aria-label={`选择场景 ${scene.name}`}
                    checked={selected.has(scene.id)}
                    disabled={busy}
                    onChange={() => toggle(scene.id)}
                  />
                )}
                <div className="scene-card-menu">
                  <ActionMenu
                    label={`场景操作 ${scene.name}`}
                    actions={[
                      {
                        label: "打开场景",
                        icon: <ArrowUpRight />,
                        onSelect: () => onOpen(scene.id),
                        disabled: busy,
                      },
                      {
                        label: "重命名",
                        icon: <Pencil />,
                        onSelect: () => edit(scene),
                        disabled: busy,
                      },
                      {
                        label: selected.has(scene.id) ? "取消选中" : "选择场景",
                        icon: <CheckSquare />,
                        onSelect: () => toggle(scene.id),
                        disabled: busy,
                      },
                      {
                        label: "删除场景",
                        icon: <Trash2 />,
                        onSelect: () => setRemove([scene]),
                        destructive: true,
                        disabled: busy,
                      },
                    ]}
                  />
                </div>
              </article>
            ))}
          </div>
        </ContextMenuTrigger>
        <ContextMenuContent onCloseAutoFocus={(e) => e.preventDefault()}>
          {targets.length === 1 && (
            <>
              <ContextMenuItem onSelect={() => onOpen(targets[0].id)}>
                <ArrowUpRight />
                打开场景
              </ContextMenuItem>
              <ContextMenuItem onSelect={() => edit(targets[0])}>
                <Pencil />
                重命名
              </ContextMenuItem>
              <ContextMenuSeparator />
            </>
          )}
          {targets.length === 1 && (
            <ContextMenuItem onSelect={() => toggle(targets[0].id)}>
              <CheckSquare />
              {selected.has(targets[0].id) ? "取消选中" : "选择场景"}
            </ContextMenuItem>
          )}
          <ContextMenuItem onSelect={all}>
            <CheckSquare />
            全选场景
          </ContextMenuItem>
          {selecting && (
            <ContextMenuItem onSelect={clear}>
              <X />
              取消选择
            </ContextMenuItem>
          )}
          <ContextMenuSeparator />
          <ContextMenuItem
            disabled={!targets.length}
            className="text-destructive"
            onSelect={() => setRemove(targets)}
          >
            <Trash2 />
            {targets.length > 1 ? `删除 ${targets.length} 个场景` : "删除场景"}
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>
      <ModalShell
        open={!!rename}
        title="重命名场景"
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
              取消
            </Button>
            <Button
              type="submit"
              form="scene-rename"
              loading={busy}
              disabled={!name.trim()}
            >
              保存
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
            aria-label="场景名称"
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
            ? `删除「${remove[0].name}」？`
            : `删除 ${remove.length} 个场景？`
        }
        body="场景、导入的模型和版本记录将永久删除，画布中的场景引用将不可用。已生成并保存到素材库的图片和视频会保留。"
        onCancel={() => {
          if (!busy) setRemove([]);
        }}
        onConfirm={() => void confirmDelete()}
      />
    </div>
  );
}
