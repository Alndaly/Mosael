/**
 * `comfy_canvas_edit` 那张确认卡上的改动清单(ADR 0042 拍板 3):点「应用」之前,用户读到的就是这一份 —— 加了哪几个节点、
 * 连了 / 断了哪几根线(换掉了谁)、改了哪几格(从多少改成多少)、子图里的改动改的是定义、这张图里用了几处。清单是插件对着画布上
 * 这张算出来的(结构化,见插件 canvas_edit),这里按读的人的语言说成人话。
 *
 * 清单里的节点能点了定位:在工作台的「助手」里,页签给了「页面引用」(MarkdownRefsContext),`#12` 就是一颗定位的按钮;别处
 * (右上角的全局确认中心)照样是字。新加的节点还没有编号,写「新节点」。
 */
import React from "react";

import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { MarkdownRefsContext } from "@/components/markdown/markdownRefs";
import { cn } from "@/lib/utils";

type Translate = ReturnType<typeof useI18n>;
type Change = Record<string, unknown> & { op: string };
interface Layer {
  id: string;
  name: string;
  uses: number;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value : value == null ? "" : String(value));

/** 一种改动怎么说。`{占位}` 换成节点、口、值(节点能点)。 */
const SENTENCES: Partial<Record<string, MessageKey>> = {
  add_node: "comfyEditAddNode",
  remove_node: "comfyEditRemoveNode",
  connect: "comfyEditConnect",
  disconnect: "comfyEditDisconnect",
  set_widget: "comfyEditSetWidget",
  set_title: "comfyEditSetTitle",
  set_position: "comfyEditSetPosition",
  add_group: "comfyEditAddGroup",
  set_group: "comfyEditSetGroup",
  remove_group: "comfyEditRemoveGroup",
  bypass: "comfyEditBypass",
  mute: "comfyEditMute",
  add_subgraph_input: "comfyEditAddInput",
  add_subgraph_output: "comfyEditAddOutput",
  remove_subgraph_io: "comfyEditRemoveIo",
  promote_widget: "comfyEditPromote",
  unpromote_widget: "comfyEditUnpromote",
  to_subgraph: "comfyEditToSubgraph",
  unpack_subgraph: "comfyEditUnpack",
};

/** 把一句文案里的 `{名字}` 换成节点(可能是按钮)。 */
function fill(template: string, slots: Record<string, React.ReactNode>): React.ReactNode[] {
  return template.split(/\{(\w+)\}/).map((part, index) => (index % 2 === 1 ? <React.Fragment key={index}>{slots[part] ?? ""}</React.Fragment> : part));
}

function NodeName({ node, type }: { node: string; type?: string }) {
  const t = useI18n();
  const refs = React.useContext(MarkdownRefsContext);
  const label = node.startsWith("$") ? t("comfyEditNewNode")
    : node === "@in" || node === "@out" ? t(node === "@in" ? "comfyEditSubgraphInput" : "comfyEditSubgraphOutput")
    : refs ? refs.render(node, `#${node}`) : <span className="font-mono">#{node}</span>;
  return (
    <>
      {label}
      {type ? <span className="text-muted-foreground"> {type}</span> : null}
    </>
  );
}

function Value({ value }: { value: unknown }) {
  return <code className="rounded-sm bg-panel-inset px-1 font-mono text-[0.95em] [overflow-wrap:anywhere]">{JSON.stringify(value) ?? ""}</code>;
}

/** 连线的一头是子图边界上的口时换一种说法(「子图的输入口「seed」」,不是「@in.seed」)。 */
function sentenceKey(change: Change, from: Record<string, unknown>, to: Record<string, unknown>): MessageKey | undefined {
  if (change.op === "connect" && from.node === "@in") return "comfyEditConnectFromInput";
  if (change.op === "connect" && to.node === "@out") return "comfyEditConnectToOutput";
  if (change.op === "disconnect" && to.node === "@out") return "comfyEditDisconnectOutput";
  return SENTENCES[change.op];
}

function sentence(t: Translate, change: Change): React.ReactNode {
  const from = isRecord(change.from) ? change.from : {};
  const to = isRecord(change.to) ? change.to : {};
  const key = sentenceKey(change, from, to);
  if (!key) return change.op;
  const node = text(change.node);
  const replaced = isRecord(change.replaces) ? change.replaces : null;
  const widgets = isRecord(change.widgets) ? Object.entries(change.widgets) : [];
  const slots: Record<string, React.ReactNode> = {
    node: <NodeName node={node} />,
    type: text(change.type),
    title: text(change.title),
    group: <span className="font-mono">{text(change.group)}</span>,
    bounds: <Value value={change.bounds} />,
    near: change.near ? <NodeName node={text(change.near)} /> : "",
    from: <NodeName node={text(from.node)} />,
    output: text(from.output),
    to: <NodeName node={text(to.node)} />,
    input: text(to.input),
    widget: text(change.widget),
    before: <Value value={change.before} />,
    after: <Value value={change.after} />,
    name: text(change.name),
    links: text(change.links ?? 0),
    value: <Value value={change.value} />,
    nodes: (Array.isArray(change.nodes) ? change.nodes : []).filter(isRecord).map((one, index) => (
      <React.Fragment key={index}>{index > 0 ? "、" : ""}<NodeName node={text(one.node)} type={text(one.type)} /></React.Fragment>
    )),
  };
  const parts: React.ReactNode[] = [fill(t(key), slots)];
  if (change.op === "add_node" && change.title) parts.push(fill(t("comfyEditTitled"), slots));
  if (change.op === "add_node" && change.near) parts.push(fill(t("comfyEditNear"), slots));
  if (change.op === "add_node" && widgets.length) {
    parts.push(" (", widgets.map(([name, value], index) => (
      <React.Fragment key={name}>{index > 0 ? ", " : ""}{name} = <Value value={value} /></React.Fragment>
    )), ")");
  }
  if ((change.op === "bypass" || change.op === "mute") && change.on === false) {
    return fill(t(change.op === "bypass" ? "comfyEditUnbypass" : "comfyEditUnmute"), slots);
  }
  if (change.op === "connect" && replaced) {
    parts.push(fill(t("comfyEditReplaces"), { old: <><NodeName node={text(replaced.node)} />.{text(replaced.output)}</> }));
  }
  if (change.op === "disconnect" && isRecord(change.from)) {
    parts.push(fill(t("comfyEditWasFrom"), { old: <><NodeName node={text(change.from.node)} />.{text(change.from.output)}</> }));
  }
  if (change.op === "to_subgraph" && change.name) parts.push(fill(t("comfyEditNamed"), slots));
  if (change.op === "unpack_subgraph" && Number(change.uses) > 1) parts.push(t("comfyEditUnpackOthers"));
  return parts;
}

/** 连着的几条改在同一层的放一组:子图那一组的头上写它在这张图里用了几处。 */
function groups(changes: Change[]): { layer: Layer | null; changes: Change[] }[] {
  const out: { layer: Layer | null; changes: Change[] }[] = [];
  for (const change of changes) {
    const layer = isRecord(change.layer) ? (change.layer as unknown as Layer) : null;
    const last = out.at(-1);
    if (last && (last.layer?.id ?? null) === (layer?.id ?? null)) last.changes.push(change);
    else out.push({ layer, changes: [change] });
  }
  return out;
}

export function CanvasEditPreview({ payload }: { payload: Record<string, unknown> }) {
  const t = useI18n();
  const changes = (Array.isArray(payload.changes) ? payload.changes : []).filter((one): one is Change => isRecord(one) && typeof one.op === "string");
  const check = isRecord(payload.check) ? payload.check : {};
  const before = isRecord(check.before) ? check.before : {};
  const after = isRecord(check.after) ? check.after : {};
  const fixed = (Array.isArray(check.fixed) ? check.fixed : []).filter(isRecord);
  const introduced = (Array.isArray(check.introduced) ? check.introduced : []).filter(isRecord);
  return (
    <div className="grid min-w-0 gap-2 text-ui-xs" data-comfy-edit-preview="">
      {groups(changes).map(({ layer, changes: items }, index) => (
        <section key={index} className="grid min-w-0 gap-1" aria-label={layer ? t("comfyEditInSubgraph").replace("{name}", layer.name) : t("comfyEditChanges")}>
          {layer && (
            <span className={cn("text-muted-foreground", layer.uses > 1 && "font-medium text-warning")} data-subgraph-uses={layer.uses}>
              {(layer.uses > 1 ? t("comfyEditInSharedSubgraph") : t("comfyEditInSubgraph"))
                .replace("{name}", layer.name).replace("{uses}", String(layer.uses))}
            </span>
          )}
          <ol className="m-0 grid min-w-0 list-decimal gap-0.5 pl-5 text-foreground marker:text-muted-foreground">
            {items.map((change, at) => (
              <li key={at} data-change={change.op} className="[overflow-wrap:anywhere]">{sentence(t, change)}</li>
            ))}
          </ol>
        </section>
      ))}
      {payload.structural === true && <p className="m-0 text-muted-foreground">{t("comfyEditStructural")}</p>}
      <p className="m-0 text-muted-foreground" data-check="">
        {t("comfyEditCheck").replace("{before}", text(before.error ?? 0)).replace("{after}", text(after.error ?? 0))
          .replace("{warningsBefore}", text(before.warning ?? 0)).replace("{warningsAfter}", text(after.warning ?? 0))}
      </p>
      {fixed.length > 0 && (
        <p className="m-0 text-success">
          {t("comfyEditFixes").replace("{n}", String(fixed.length))}
          {fixed.slice(0, 5).map((one, index) => (
            <React.Fragment key={index}>{index > 0 ? ";" : " "}{one.ref ? <NodeName node={text(one.ref)} /> : null} {text(one.cause)}</React.Fragment>
          ))}
        </p>
      )}
      {introduced.length > 0 && (
        <p className="m-0 text-warning">
          {t("comfyEditWarns").replace("{n}", String(introduced.length))}
          {introduced.slice(0, 5).map((one, index) => (
            <React.Fragment key={index}>{index > 0 ? ";" : " "}{one.ref ? <NodeName node={text(one.ref)} /> : null} {text(one.cause)}</React.Fragment>
          ))}
        </p>
      )}
    </div>
  );
}
