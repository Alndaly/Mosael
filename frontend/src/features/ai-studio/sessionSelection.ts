export function agentSessionSelectionKey(workspaceId: string): string {
  return `mibu.agent.session.${workspaceId}`;
}

export function generationSessionSelectionKey(workspaceId: string): string {
  return `mibu.generation.session.${workspaceId}`;
}
