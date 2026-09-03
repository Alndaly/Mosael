import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { importAsset } from "@/api/client";
import { Recorder } from "@/features/editor/Recorder";

type RecordingDestination = {
  projectId?: string;
};

type ActiveRecordingDestination = RecordingDestination & {
  workspaceId: string;
};

type RecordingContextValue = {
  openRecorder: (destination?: RecordingDestination) => void;
};

const RecordingContext = React.createContext<RecordingContextValue | null>(null);

export function useRecorder(): RecordingContextValue {
  const context = React.useContext(RecordingContext);
  if (!context) throw new Error("useRecorder must be used within RecordingProvider");
  return context;
}

/**
 * Owns the capture session above individual workspace pages so navigation cannot
 * unmount an in-progress recording. The destination is captured when recording
 * opens; navigating to another project must never redirect the finished files.
 */
export function RecordingProvider({
  workspaceId,
  children,
}: React.PropsWithChildren<{ workspaceId: string }>) {
  const queryClient = useQueryClient();
  const [destination, setDestination] = React.useState<ActiveRecordingDestination | null>(null);

  const uploadRecording = useMutation({
    mutationFn: ({ target, file }: { target: ActiveRecordingDestination; file: File }) =>
      importAsset({ workspaceId: target.workspaceId, projectId: target.projectId, file }),
    onSuccess: (_asset, variables) =>
      queryClient.invalidateQueries({ queryKey: ["assets", variables.target.workspaceId] }),
  });

  const openRecorder = React.useCallback(
    (next: RecordingDestination = {}) => {
      // An active session owns its original destination until it closes.
      setDestination((current) => current ?? { workspaceId, ...next });
    },
    [workspaceId],
  );

  const value = React.useMemo(() => ({ openRecorder }), [openRecorder]);

  return (
    <RecordingContext.Provider value={value}>
      {children}
      <Recorder
        open={destination !== null}
        onOpenChange={(open) => {
          if (!open) setDestination(null);
        }}
        onRecorded={(files) => {
          if (!destination) return;
          for (const file of files) uploadRecording.mutate({ target: destination, file });
        }}
      />
    </RecordingContext.Provider>
  );
}
