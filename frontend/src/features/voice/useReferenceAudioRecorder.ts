import React from "react";

export type ReferenceAudioRecordingError = "denied" | "empty" | "failed";

const MIN_RECORDING_BYTES = 1024;

function recordingExtension(mimeType: string) {
  const type = mimeType.toLowerCase();
  if (type.includes("ogg")) return "ogg";
  if (type.includes("mp4")) return "m4a";
  if (type.includes("wav")) return "wav";
  return "webm";
}

function isPermissionError(error: unknown) {
  if (!error || typeof error !== "object" || !("name" in error)) return false;
  return error.name === "NotAllowedError" || error.name === "PermissionDeniedError";
}

/**
 * 录一段声音克隆用的参考音频。
 *
 * 剪辑页和设置页都只消费最终的 `File`；麦克风权限、计时、MediaRecorder 收尾和轨道释放必须
 * 只有一份实现。特别是弹窗关闭/页签切换时要主动停掉硬件轨道，否则浏览器的麦克风占用提示会
 * 一直亮着，下一次录制也可能拿不到设备。
 */
export function useReferenceAudioRecorder({
  onRecorded,
  onError,
}: {
  onRecorded: (file: File) => void;
  onError: (error: ReferenceAudioRecordingError) => void;
}) {
  const [recording, setRecording] = React.useState(false);
  const [starting, setStarting] = React.useState(false);
  const [seconds, setSeconds] = React.useState(0);
  const recorderRef = React.useRef<MediaRecorder | null>(null);
  const streamRef = React.useRef<MediaStream | null>(null);
  const timerRef = React.useRef<number | null>(null);
  const requestRef = React.useRef(0);
  const onRecordedRef = React.useRef(onRecorded);
  const onErrorRef = React.useRef(onError);
  onRecordedRef.current = onRecorded;
  onErrorRef.current = onError;

  const stopTimer = React.useCallback(() => {
    if (timerRef.current !== null) window.clearInterval(timerRef.current);
    timerRef.current = null;
  }, []);

  const releaseStream = React.useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const cancel = React.useCallback(() => {
    requestRef.current += 1;
    const recorder = recorderRef.current;
    recorderRef.current = null;
    if (recorder && recorder.state !== "inactive") {
      recorder.ondataavailable = null;
      recorder.onstop = null;
      recorder.onerror = null;
      recorder.stop();
    }
    stopTimer();
    releaseStream();
    setStarting(false);
    setRecording(false);
    setSeconds(0);
  }, [releaseStream, stopTimer]);

  const start = React.useCallback(async () => {
    if (recorderRef.current || starting || recording) return;
    const request = requestRef.current + 1;
    requestRef.current = request;
    setStarting(true);
    let stream: MediaStream | null = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (request !== requestRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      const recorder = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      streamRef.current = stream;
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      recorder.onstop = () => {
        const type = recorder.mimeType || "audio/webm";
        const blob = new Blob(chunks, { type });
        recorderRef.current = null;
        stopTimer();
        releaseStream();
        setRecording(false);
        setSeconds(0);
        if (blob.size < MIN_RECORDING_BYTES) {
          onErrorRef.current("empty");
          return;
        }
        onRecordedRef.current(new File([blob], `recording-${Date.now()}.${recordingExtension(type)}`, { type }));
      };
      recorder.onerror = () => {
        recorder.onstop = null;
        recorderRef.current = null;
        stopTimer();
        releaseStream();
        setRecording(false);
        setSeconds(0);
        onErrorRef.current("failed");
      };
      recorder.start(1000);
      setSeconds(0);
      setRecording(true);
      timerRef.current = window.setInterval(() => setSeconds((current) => current + 1), 1000);
    } catch (error) {
      recorderRef.current = null;
      streamRef.current = null;
      stopTimer();
      stream?.getTracks().forEach((track) => track.stop());
      setRecording(false);
      setSeconds(0);
      if (request === requestRef.current) {
        onErrorRef.current(isPermissionError(error) ? "denied" : "failed");
      }
    } finally {
      if (request === requestRef.current) setStarting(false);
    }
  }, [recording, releaseStream, starting, stopTimer]);

  const stop = React.useCallback(() => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    stopTimer();
    setRecording(false);
    recorder.stop();
  }, [stopTimer]);

  React.useEffect(
    () => () => {
      requestRef.current += 1;
      const recorder = recorderRef.current;
      if (recorder && recorder.state !== "inactive") {
        recorder.ondataavailable = null;
        recorder.onstop = null;
        recorder.onerror = null;
        recorder.stop();
      }
      stopTimer();
      releaseStream();
    },
    [releaseStream, stopTimer],
  );

  return { recording, starting, seconds, start, stop, cancel };
}
