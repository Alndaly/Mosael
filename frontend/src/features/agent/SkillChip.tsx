import React from "react";
import { Node, NodeViewWrapper, ReactNodeViewRenderer, mergeAttributes, type JSONContent } from "@tiptap/react";
import { Sparkles } from "lucide-react";

import { listSkills, type AgentSkill } from "@/api/client";
import { Truncate } from "@/components/ui/truncate";
import { cn } from "@/lib/utils";

/**
 * 输入框里用「/」点名的技能(ADR 0040 §4)。
 *
 * 和 `@` 引用一样是**原子节点**:退格不会咬掉半个名字。序列化成 `/显示名` —— 那是给模型读的那句话
 * (「/做带货短视频 帮我做一条」读起来是人话);真正点名用的是 `ref`,另收进消息的 `skills`,后端照它把技能
 * 全文挂到这一轮。和引用分开存,因为它们是两件事:引用是「我说的是这个对象」,技能是「这一轮照这个做法做」。
 */
export const SKILL_NODE = "agentSkill";

/** 一条消息最多点名几个技能 —— 和后端 `runtime.MAX_FORCED_SKILLS` 同一个数(每个都是整份正文挂进这一轮)。 */
export const MAX_FORCED_SKILLS = 3;

/** 「/」菜单里的一条。 */
export interface SkillOption {
  ref: string;
  title: string;
  description: string;
  /** 来源,说给人听的那句(「Mosael 内置」「从 brand.zip 导入」)。 */
  sourceLabel: string;
}

/** 菜单里一次摆几条。 */
export const SKILL_MENU_LIMIT = 12;

/**
 * 列表在手边留一会儿:打一个字菜单就重问一遍的话,每次都先闪一下「没有开着的技能」再出候选。
 * 只留十几秒 —— 在设置里刚开的技能,回到对话很快就该在菜单里。
 */
const SKILL_LIST_TTL_MS = 15_000;
const recent = new Map<string, { at: number; list: Promise<AgentSkill[]> }>();

function skillList(workspaceId: string): Promise<AgentSkill[]> {
  const hit = recent.get(workspaceId);
  if (hit && Date.now() - hit.at < SKILL_LIST_TTL_MS) return hit.list;
  const list = listSkills(workspaceId).catch(() => {
    recent.delete(workspaceId);
    return [] as AgentSkill[];
  });
  recent.set(workspaceId, { at: Date.now(), list });
  return list;
}

/** 能点名的技能:**开着、能用**的那些。名字、显示名、说明里任何一处对得上就算。 */
export async function searchSkills(workspaceId: string, query: string): Promise<SkillOption[]> {
  const needle = query.trim().toLowerCase();
  const skills = await skillList(workspaceId);
  return skills
    .filter((skill) => skill.enabled && !skill.problem)
    .filter((skill) => !needle || [skill.ref, skill.title, skill.description].some((text) => text.toLowerCase().includes(needle)))
    .slice(0, SKILL_MENU_LIMIT)
    .map((skill) => ({ ref: skill.ref, title: skill.title, description: skill.description, sourceLabel: skill.source_label }));
}

/** 文档里点名的技能,按出现顺序去重,最多 MAX_FORCED_SKILLS 个。 */
export function collectSkills(document: JSONContent | undefined): string[] {
  const out: string[] = [];
  const walk = (node: JSONContent | undefined) => {
    if (!node) return;
    if (node.type === SKILL_NODE) {
      const ref = String((node.attrs as { ref?: string } | undefined)?.ref ?? "");
      if (ref && !out.includes(ref)) out.push(ref);
    }
    for (const child of node.content ?? []) walk(child);
  };
  walk(document);
  return out.slice(0, MAX_FORCED_SKILLS);
}

/** 胶囊本身。输入框里和发出去之后的气泡里用同一个。 */
export function SkillBadge({ title, refName, className }: { title: string; refName: string; className?: string }) {
  return (
    <span
      data-agent-skill={refName}
      className={cn(
        "inline-flex max-w-[220px] items-center gap-1 rounded-md border border-[color-mix(in_srgb,var(--primary)_35%,transparent)] bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] px-1 py-0.5 align-baseline text-ui-2xs text-foreground",
        className,
      )}
    >
      <Sparkles size={11} className="shrink-0 text-primary" aria-hidden />
      <Truncate>{`/${title || refName}`}</Truncate>
    </span>
  );
}

function EditorSkillChip({ node }: { node: { attrs: Record<string, unknown> } }) {
  return (
    <NodeViewWrapper as="span" data-agent-skill-node="">
      <SkillBadge title={String(node.attrs.title ?? "")} refName={String(node.attrs.ref ?? "")} />
    </NodeViewWrapper>
  );
}

export const SkillChip = Node.create({
  name: SKILL_NODE,
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  addAttributes: () => ({ ref: { default: "" }, title: { default: "" } }),
  parseHTML: () => [{ tag: "span[data-agent-skill-node]" }],
  renderHTML: ({ HTMLAttributes }: { HTMLAttributes: Record<string, unknown> }) => [
    "span",
    mergeAttributes(HTMLAttributes, { "data-agent-skill-node": "" }),
  ],
  renderText: ({ node }: { node: { attrs: Record<string, unknown> } }) =>
    `/${String(node.attrs.title ?? "") || String(node.attrs.ref ?? "")}`,
  addNodeView: () => ReactNodeViewRenderer(EditorSkillChip),
});
