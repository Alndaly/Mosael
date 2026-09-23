/**
 * 知识点讲解视频:标题 → 一节一节讲 → 要点回顾。
 *
 * 给的是**内容**(标题、每节的要点 / 公式 / 代码 / 提示),不是时间轴 —— 每一段多长由内容
 * 算出来(`timeline`),`calculateMetadata` 用同一份结果定总长。写成两份的话,
 * 画面和总长迟早对不上:最后一节被截掉,或者结尾空转几秒。
 */
import katex from "katex";
import "katex/dist/katex.min.css";
import React from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  Sequence,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

import { accentOf, MONO, palette, type Palette, SANS, type ThemeName } from "./theme";

export type Section = {
  heading: string;
  points?: string[];
  formula?: string;
  code?: string;
  note?: string;
};

export type ExplainerProps = {
  title: string;
  subtitle?: string;
  label?: string;
  sections: Section[];
  summary?: string[];
  summaryTitle?: string;
  theme?: ThemeName;
  accent?: string;
  width: number;
  height: number;
  fps: number;
};

/** 每一种内容要给观众多少秒。按「读得完」定,不按「看着热闹」定。 */
const SECONDS = {
  title: 3.5,
  heading: 1.4,
  point: 1.9,
  formula: 3.2,
  codeBase: 1.6,
  codeLine: 0.45,
  note: 2.6,
  hold: 1.2,
  summaryBase: 1.8,
  summaryItem: 1.5,
};

type Block =
  | { kind: "title" }
  | { kind: "section"; index: number }
  | { kind: "summary" };

export type Timeline = { blocks: Array<Block & { from: number; duration: number }>; total: number };

function sectionSeconds(section: Section): number {
  const codeLines = section.code ? section.code.split("\n").length : 0;
  return (
    SECONDS.heading +
    (section.points?.length ?? 0) * SECONDS.point +
    (section.formula ? SECONDS.formula : 0) +
    (section.code ? SECONDS.codeBase + Math.min(codeLines, 24) * SECONDS.codeLine : 0) +
    (section.note ? SECONDS.note : 0) +
    SECONDS.hold
  );
}

export function timeline(props: Pick<ExplainerProps, "sections" | "summary" | "fps">): Timeline {
  const seconds: Array<[Block, number]> = [[{ kind: "title" }, SECONDS.title]];
  props.sections.forEach((section, index) => seconds.push([{ kind: "section", index }, sectionSeconds(section)]));
  if (props.summary?.length) {
    seconds.push([{ kind: "summary" }, SECONDS.summaryBase + props.summary.length * SECONDS.summaryItem]);
  }
  let from = 0;
  const blocks = seconds.map(([block, length]) => {
    const duration = Math.round(length * props.fps);
    const placed = { ...block, from, duration };
    from += duration;
    return placed;
  });
  return { blocks, total: from };
}

/** 进场:淡入 + 上移。所有元素共用这一种动作,画面才像一个人做的。
 *  写成组件而不是 hook:元素是按内容**有条件**出现的,hook 不能放在条件里。 */
function Enter({ delay, style, children }: { delay: number; style?: React.CSSProperties; children?: React.ReactNode }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const progress = spring({ frame: frame - delay, fps, config: { damping: 200 }, durationInFrames: Math.round(fps * 0.6) });
  return (
    <div style={{ ...style, opacity: progress, transform: `translateY(${interpolate(progress, [0, 1], [24, 0])}px)` }}>
      {children}
    </div>
  );
}

/** 一段结束前的淡出,相邻两段之间不硬切。 */
function useExit(duration: number): number {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return interpolate(frame, [duration - fps * 0.4, duration], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.in(Easing.quad),
  });
}

function Backdrop({ colors }: { colors: Palette }) {
  const { width, height } = useVideoConfig();
  const step = Math.min(width, height) / 24;
  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(ellipse at 20% 0%, ${colors.glow}, transparent 55%), linear-gradient(160deg, ${colors.background}, ${colors.backgroundEdge})`,
      }}
    >
      <AbsoluteFill
        style={{
          backgroundImage: `radial-gradient(${colors.grid} 1.5px, transparent 1.5px)`,
          backgroundSize: `${step}px ${step}px`,
        }}
      />
    </AbsoluteFill>
  );
}

function Formula({ tex, unit, colors }: { tex: string; unit: number; colors: Palette }) {
  // throwOnError: false —— 一处 LaTeX 写错,整段视频不该渲不出来;KaTeX 会把出错的那一截标红显示。
  const html = katex.renderToString(tex, { displayMode: true, throwOnError: false, output: "html" });
  return (
    <div
      style={{
        background: colors.card, border: `1px solid ${colors.cardBorder}`, borderRadius: 24 * unit,
        padding: `${28 * unit}px ${40 * unit}px`, fontSize: 54 * unit, color: colors.text,
      }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function CodeBlock({ code, unit, colors, startFrame }: { code: string; unit: number; colors: Palette; startFrame: number }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const lines = code.split("\n").slice(0, 24);
  const shown = Math.max(0, Math.floor((frame - startFrame) / (fps * SECONDS.codeLine)) + 1);
  return (
    <div
      style={{
        background: colors.card, border: `1px solid ${colors.cardBorder}`, borderRadius: 20 * unit,
        padding: `${24 * unit}px ${32 * unit}px`, fontFamily: MONO, fontSize: 30 * unit, lineHeight: 1.55,
        color: colors.text, whiteSpace: "pre",
      }}
    >
      {lines.map((line, index) => (
        <div key={index} style={{ opacity: index < shown ? 1 : 0.12, transition: "none" }}>
          <span style={{ color: colors.muted, display: "inline-block", width: 48 * unit }}>{index + 1}</span>
          {line || " "}
        </div>
      ))}
    </div>
  );
}

function TitleCard({ props, colors, unit, duration }: { props: ExplainerProps; colors: Palette; unit: number; duration: number }) {
  const exit = useExit(duration);
  return (
    <AbsoluteFill style={{ justifyContent: "center", padding: `0 ${120 * unit}px`, opacity: exit }}>
      {props.label ? (
        <Enter delay={0} style={{ color: colors.accent, fontSize: 32 * unit, fontWeight: 600, letterSpacing: 2 * unit, marginBottom: 24 * unit }}>
          {props.label}
        </Enter>
      ) : null}
      <Enter delay={6} style={{ color: colors.text, fontSize: 96 * unit, fontWeight: 700, lineHeight: 1.15 }}>{props.title}</Enter>
      {props.subtitle ? (
        <Enter delay={14} style={{ color: colors.muted, fontSize: 40 * unit, marginTop: 28 * unit, lineHeight: 1.4 }}>{props.subtitle}</Enter>
      ) : null}
      <Enter delay={20} style={{ width: 120 * unit, height: 8 * unit, borderRadius: 4 * unit, background: colors.accent, marginTop: 48 * unit }} />
    </AbsoluteFill>
  );
}

function SectionCard({
  section, index, count, colors, unit, duration,
}: { section: Section; index: number; count: number; colors: Palette; unit: number; duration: number }) {
  const { fps } = useVideoConfig();
  const exit = useExit(duration);
  // 各部分依次出场:标题 → 要点逐条 → 公式 → 代码 → 提示。起点按同一份 SECONDS 累加。
  let at = SECONDS.heading * fps * 0.6;
  const pointStarts = (section.points ?? []).map(() => {
    const start = at;
    at += SECONDS.point * fps;
    return start;
  });
  const formulaStart = at;
  if (section.formula) at += SECONDS.formula * fps;
  const codeStart = at;
  if (section.code) at += (SECONDS.codeBase + Math.min(section.code.split("\n").length, 24) * SECONDS.codeLine) * fps;
  const noteStart = at;
  return (
    // 垂直居中:每个元素出场前就占着位置(只是透明),所以居中不会让版面随出场跳动。
    <AbsoluteFill style={{ justifyContent: "center", padding: `${110 * unit}px ${120 * unit}px`, opacity: exit, gap: 36 * unit }}>
      <Enter delay={0} style={{ color: colors.accent, fontSize: 28 * unit, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
        {String(index + 1).padStart(2, "0")} / {String(count).padStart(2, "0")}
      </Enter>
      <Enter delay={4} style={{ color: colors.text, fontSize: 68 * unit, fontWeight: 700, lineHeight: 1.2 }}>{section.heading}</Enter>
      <div style={{ display: "flex", flexDirection: "column", gap: 22 * unit, marginTop: 8 * unit }}>
        {(section.points ?? []).map((point, i) => (
          <Point key={i} text={point} start={pointStarts[i]} colors={colors} unit={unit} />
        ))}
      </div>
      {section.formula ? (
        <Enter delay={formulaStart}>
          <Formula tex={section.formula} unit={unit} colors={colors} />
        </Enter>
      ) : null}
      {section.code ? (
        <Enter delay={codeStart}>
          <CodeBlock code={section.code} unit={unit} colors={colors} startFrame={codeStart} />
        </Enter>
      ) : null}
      {section.note ? (
        <Enter
          delay={noteStart}
          style={{
            background: colors.accentSoft, borderRadius: 18 * unit,
            padding: `${22 * unit}px ${30 * unit}px`, color: colors.text, fontSize: 36 * unit, lineHeight: 1.45,
          }}
        >
          {section.note}
        </Enter>
      ) : null}
    </AbsoluteFill>
  );
}

function Point({ text, start, colors, unit }: { text: string; start: number; colors: Palette; unit: number }) {
  return (
    <Enter delay={start} style={{ display: "flex", gap: 24 * unit, alignItems: "baseline" }}>
      <div style={{ flex: "none", width: 16 * unit, height: 16 * unit, borderRadius: 8 * unit, background: colors.accent, transform: `translateY(${-4 * unit}px)` }} />
      <div style={{ color: colors.text, fontSize: 44 * unit, lineHeight: 1.45 }}>{text}</div>
    </Enter>
  );
}

function SummaryCard({ props, colors, unit, duration }: { props: ExplainerProps; colors: Palette; unit: number; duration: number }) {
  const { fps } = useVideoConfig();
  const exit = useExit(duration);
  return (
    <AbsoluteFill style={{ justifyContent: "center", padding: `0 ${120 * unit}px`, opacity: exit, gap: 30 * unit }}>
      <Enter delay={0} style={{ color: colors.accent, fontSize: 32 * unit, fontWeight: 600 }}>{props.summaryTitle || "要点回顾"}</Enter>
      {(props.summary ?? []).map((item, i) => (
        <Point key={i} text={item} start={SECONDS.summaryBase * fps * 0.5 + i * SECONDS.summaryItem * fps} colors={colors} unit={unit} />
      ))}
    </AbsoluteFill>
  );
}

function Progress({ colors, unit, total }: { colors: Palette; unit: number; total: number }) {
  const frame = useCurrentFrame();
  return (
    <div style={{ position: "absolute", left: 0, bottom: 0, height: 8 * unit, width: `${(frame / Math.max(total - 1, 1)) * 100}%`, background: colors.accent }} />
  );
}

export const Explainer: React.FC<ExplainerProps> = (props) => {
  const { width, height } = useVideoConfig();
  // 版式按「短边 = 1080」设计。竖屏的短边是宽,于是字和横屏一样大、上下却多出将近一倍 ——
  // 竖屏整体放大 1.3 倍,让画面被内容撑起来,而不是一小块字漂在中间。
  const unit = (Math.min(width, height) / 1080) * (height > width ? 1.3 : 1);
  const colors = palette(props.theme ?? "dark", accentOf(props.accent));
  const plan = timeline(props);
  return (
    <AbsoluteFill style={{ fontFamily: SANS }}>
      <Backdrop colors={colors} />
      {plan.blocks.map((block) => (
        <Sequence key={`${block.kind}-${block.from}`} from={block.from} durationInFrames={block.duration}>
          {block.kind === "title" ? (
            <TitleCard props={props} colors={colors} unit={unit} duration={block.duration} />
          ) : block.kind === "section" ? (
            <SectionCard
              section={props.sections[block.index]} index={block.index} count={props.sections.length}
              colors={colors} unit={unit} duration={block.duration}
            />
          ) : (
            <SummaryCard props={props} colors={colors} unit={unit} duration={block.duration} />
          )}
        </Sequence>
      ))}
      <Progress colors={colors} unit={unit} total={plan.total} />
    </AbsoluteFill>
  );
};
