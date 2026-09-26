import React from "react";
import { assetKeys } from "@/api/queryKeys";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { importAsset } from "@/api/client";
import { Recorder } from "./Recorder";
import { RecordingContext, type RecordingDestination } from "./recordingContext";


type ActiveRecordingDestination = RecordingDestination & {
  workspaceId: string;
};


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
      queryClient.invalidateQueries({ queryKey: assetKeys.all(variables.target.workspaceId) }),
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
