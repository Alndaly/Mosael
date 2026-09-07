/** Remember explicit scene routes per workspace; returning to the list clears the detail. */
export class SceneRouteMemory {
  private routes = new Map<string, string>();

  visit(workspaceId: string, hash: string) {
    if (/^#\/scenes(?:\?|$)/.test(hash)) this.routes.set(workspaceId, hash);
  }

  restore(workspaceId: string) {
    return this.routes.get(workspaceId) ?? "#/scenes";
  }
}
