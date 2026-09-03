/**
 * Compatibility assembly for application API imports.
 *
 * Feature code may keep importing from `@/api/client`, while each implementation lives in
 * a cohesive domain module that depends only on the shared HTTP transport (and explicit
 * domain types where needed). New endpoint families belong in `domains/*`, not in this file.
 */
export * from "@/api/transport";
export * from "@/api/domains/assets";
export * from "@/api/domains/boards";
export * from "@/api/domains/browser";
export * from "@/api/domains/editor";
export * from "@/api/domains/generation";
export * from "@/api/domains/identity";
export * from "@/api/domains/jobs";
export * from "@/api/domains/notifications";
export * from "@/api/domains/publish";
export * from "@/api/domains/scheduler";
export * from "@/api/domains/sessions";
export * from "@/api/domains/speech";
export * from "@/api/domains/workflows";
export * from "@/api/domains/workspaces";
