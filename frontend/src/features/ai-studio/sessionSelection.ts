export function agentSessionSelectionKey(workspaceId: string): string {
  return `openstudio.agent.session.${workspaceId}`;
}

export function generationSessionSelectionKey(workspaceId: string): string {
  return `openstudio.generation.session.${workspaceId}`;
}
