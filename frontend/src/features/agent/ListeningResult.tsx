import React from "react";

import { assetSpectrogramUrl } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Truncate } from "@/components/ui/truncate";
import { cn } from "@/lib/utils";

/**
 * `listen_to_audio` 的结果卡(ADR 0103):每段一块 —— 名字和几个关键数、问题清单(带时间点)、频谱图;
 * 两段以上时末尾一行行写出两两的差别。
 *
 * 只画一层:段与段之间一条分隔线,不再给每段套框。数字照后端原样显示,单位写在旁边 —— 这张卡是给人
 * 核对「智能体说的那个问题在哪」用的,不是另一份解读。
 */

type Finding = { kind: string; severity: "high" | "medium" | "low"; message: string; at: number[] };
type Report = {
  asset_id: string;
  name: string;
  seconds: number;
  requested?: { start: number; end: number | null };
  loudness: { integrated: number | null; true_peak: number | null };
  rhythm: { bpm: number | null };
  timbre: { pitch_hz: number | null; voiced_ratio: number };
  findings: Finding[];
};
type Pair = {
  a: string;
  b: string;
  brightness_ratio: number | null;
  pitch_semitones: number | null;
  loudness_diff_lu: number | null;
  timbre_distance: number;
};

export type ListeningValue = { listening: Report[]; comparison?: Pair[] };

export function isListening(value: Record<string, unknown>): value is ListeningValue {
  return (
    Array.isArray(value.listening) &&
    value.listening.length > 0 &&
    value.listening.every(
      (one) => typeof one === "object" && one !== null && "asset_id" in one && "loudness" in one && Array.isArray((one as Report).findings),
    )
  );
}

const SEVERITY_DOT: Record<Finding["severity"], string> = {
  high: "bg-destructive",
  medium: "bg-warning",
  low: "bg-muted-foreground",
};

function clock(seconds: number): string {
  const whole = Math.max(0, seconds);
  const minutes = Math.floor(whole / 60);
  return `${minutes}:${(whole % 60).toFixed(1).padStart(4, "0")}`;
}

function signed(value: number, digits = 1): string {
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

function ClipFacts({ report }: { report: Report }) {
  const t = useI18n();
  const facts = [
    clock(report.seconds),
    report.loudness.integrated != null ? `${report.loudness.integrated.toFixed(1)} LUFS` : t("listenResultSilent"),
    report.loudness.true_peak != null ? `${t("listenResultPeak")} ${report.loudness.true_peak.toFixed(1)} dBTP` : null,
    report.rhythm.bpm != null ? `${Math.round(report.rhythm.bpm)} BPM` : null,
    report.timbre.pitch_hz != null && report.timbre.voiced_ratio >= 0.3 ? `${Math.round(report.timbre.pitch_hz)} Hz` : null,
  ].filter(Boolean);
  return <span className="shrink-0 text-ui-xs tabular-nums text-muted-foreground">{facts.join(" · ")}</span>;
}

function Clip({ report }: { report: Report }) {
  const t = useI18n();
  const [pictureFailed, setPictureFailed] = React.useState(false);
  const window = report.requested ?? { start: 0, end: null };
  return (
    <li className="grid gap-2 border-t border-border pt-3 first:border-t-0 first:pt-0">
      <div className="flex min-w-0 items-baseline gap-2">
        <Truncate className="flex-1 text-ui-sm text-foreground">{report.name}</Truncate>
        <ClipFacts report={report} />
      </div>
      {report.findings.length === 0 ? (
        <p className="m-0 text-ui-xs text-muted-foreground">{t("listenResultClean")}</p>
      ) : (
        <ul className="m-0 grid list-none gap-1 p-0">
          {report.findings.map((finding) => (
            <li key={finding.kind} className="flex items-start gap-2 text-ui-xs leading-normal">
              <span aria-hidden className={cn("mt-1.5 size-1.5 shrink-0 rounded-full", SEVERITY_DOT[finding.severity])} />
              <span className="min-w-0 flex-1 text-foreground">
                {finding.message}
                {finding.at.length > 0 && (
                  <span className="ml-1 tabular-nums text-muted-foreground">{finding.at.map(clock).join(t("listenResultTimesSeparator"))}</span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {!pictureFailed && (
        <img
          className="block w-full rounded-md bg-muted"
          src={assetSpectrogramUrl(report.asset_id, window.start, window.end)}
          alt={t("listenResultSpectrogram").replace("{name}", report.name)}
          loading="lazy"
          onError={() => setPictureFailed(true)}
        />
      )}
    </li>
  );
}

function Comparison({ pairs, names }: { pairs: Pair[]; names: Map<string, string> }) {
  const t = useI18n();
  return (
    <ul className="m-0 grid list-none gap-1 border-t border-border p-0 pt-3">
      {pairs.map((pair) => {
        const parts = [
          pair.brightness_ratio != null ? `${t("listenResultBrightness")} ×${pair.brightness_ratio.toFixed(2)}` : null,
          pair.pitch_semitones != null ? `${t("listenResultPitch")} ${signed(pair.pitch_semitones)} ${t("listenResultSemitones")}` : null,
          pair.loudness_diff_lu != null ? `${t("listenResultLoudness")} ${signed(pair.loudness_diff_lu)} LU` : null,
          `${t("listenResultDistance")} ${pair.timbre_distance.toFixed(2)}`,
        ].filter(Boolean);
        return (
          <li key={`${pair.a}-${pair.b}`} className="grid gap-1 text-ui-xs">
            <Truncate className="text-foreground">{`${names.get(pair.a) ?? pair.a} → ${names.get(pair.b) ?? pair.b}`}</Truncate>
            <span className="tabular-nums text-muted-foreground">{parts.join(" · ")}</span>
          </li>
        );
      })}
    </ul>
  );
}

export function ListeningResult({ value }: { value: ListeningValue }) {
  const names = new Map(value.listening.map((report) => [report.asset_id, report.name]));
  return (
    <div className="grid gap-3">
      <ul className="m-0 grid list-none gap-3 p-0">
        {value.listening.map((report) => (
          <Clip key={report.asset_id} report={report} />
        ))}
      </ul>
      {value.comparison && value.comparison.length > 0 && <Comparison pairs={value.comparison} names={names} />}
    </div>
  );
}
