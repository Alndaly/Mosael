import React from "react";

/**
 * 录音的 context 和取它的 hook,**单独一个文件,只依赖 React**。
 *
 * 此前它们和 RecordingProvider(组件)住在一起,而那个文件又经 Recorder 引着下拉、按钮这些 UI。
 * 开发时改任何一个被引到的 UI 组件,热更新就得把那个文件整个重跑 —— 它同时导出组件和 hook,
 * React Fast Refresh 没法只换组件 —— `createContext` 于是又造了一个**新的** context:
 * 外层的 Provider 还是旧的那个,随后才加载的剪辑页拿到的是新的,整页报
 * 「useRecorder must be used within RecordingProvider」。
 *
 * context 的身份必须活过 UI 的改动,所以它待在一个 UI 改动碰不到的模块里。
 */

export type RecordingDestination = {
  projectId?: string;
};

export type RecordingContextValue = {
  openRecorder: (destination?: RecordingDestination) => void;
};

export const RecordingContext = React.createContext<RecordingContextValue | null>(null);

export function useRecorder(): RecordingContextValue {
  const context = React.useContext(RecordingContext);
  if (!context) throw new Error("useRecorder must be used within RecordingProvider");
  return context;
}
