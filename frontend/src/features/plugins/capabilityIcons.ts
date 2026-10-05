import {
  AudioLines,
  AudioWaveform,
  Boxes,
  Captions,
  FileText,
  Languages,
  Link2,
  Mic,
  Puzzle,
  Sparkles,
  Workflow,
  Wrench,
  type LucideIcon,
} from "lucide-react";

/**
 * 宿主能力(清单 `provides` 里那几个词)在界面上用哪个图标。
 *
 * 名字和「用在哪」只有后端那一份(见 capabilityTerms);图标是界面自己的事,所以只在这里。
 * 认不出的词(后端新加了一项、这里还没跟上)给一块通用的拼图 —— 照样排得进去,不留空、不报错。
 */
const ICONS: Record<string, LucideIcon> = {
  generation: Sparkles,
  tools: Wrench,
  model_library: Boxes,
  workflow_library: Workflow,
  document_parse: FileText,
  public_url: Link2,
  audio_denoise: AudioWaveform,
  audio_separation: AudioLines,
  transcription: Captions,
  translation: Languages,
  speech: Mic,
};

export function capabilityIcon(name: string): LucideIcon {
  return ICONS[name] ?? Puzzle;
}
