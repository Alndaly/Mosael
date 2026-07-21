export interface WorkflowAgentSessionRef {
  id: string;
}

export function mergeWorkflowAgentSessions<T extends WorkflowAgentSessionRef>(
  defaultSession: T | null | undefined,
  sessions: readonly T[] | null | undefined,
): T[] {
  const list = [...(sessions ?? [])];
  if (!defaultSession || list.some((item) => item.id === defaultSession.id)) return list;
  return [defaultSession, ...list];
}

export function resolveWorkflowAgentSession<T extends WorkflowAgentSessionRef>(
  selectedId: string | null,
  defaultSession: T | null | undefined,
  sessions: readonly T[] | null | undefined,
): T | null {
  const list = mergeWorkflowAgentSessions(defaultSession, sessions);
  return (
    list.find((item) => item.id === selectedId) ??
    list.find((item) => item.id === defaultSession?.id) ??
    defaultSession ??
    list[0] ??
    null
  );
}

export function nextWorkflowAgentSessionAfterDelete<T extends WorkflowAgentSessionRef>(
  deletedId: string,
  defaultSession: T | null | undefined,
  sessions: readonly T[] | null | undefined,
): T | null {
  return mergeWorkflowAgentSessions(defaultSession, sessions).find((item) => item.id !== deletedId) ?? null;
}
