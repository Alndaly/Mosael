export function agentSessionSelectionKey(workspaceId: string): string {
  return `mosael.agent.session.${workspaceId}`;
}

export function generationSessionSelectionKey(workspaceId: string): string {
  return `mosael.generation.session.${workspaceId}`;
}
