"use client";

/**
 * 管理台唯一的取数入口。**同一份表只读这一份缓存**:
 * 概览卡片、账号、模型、供应商、通道、套餐、订单、用量、审计各一个键(见 `lib/queryKeys.ts`)。
 *
 * 写操作不在这里包 mutation:管理动作完成后由调用点按影响面点名
 * `invalidateQueries` —— 例如改供应商会同时刷供应商、通道、模型(可用通道路由变了)和概览。
 * 管理员退出登录时整组 `removeQueries`,不从缓存里留给下一个登录的人。
 */
import { useQuery } from "@tanstack/react-query";

import { cloudAdmin } from "@/lib/cloud";

import { queryKeys } from "./queryKeys";

/**
 * 写操作后的缓存失效表。**新增 / 删除 / 编辑一律从这里选一行**:
 * - 账号(角色 / 积分 / 订阅 / 重置密码)→ 账号、概览、审计
 * - 模型 → 模型、概览、审计
 * - 供应商 → 供应商、通道(名字 / 地址)、模型(可用路由)、概览、审计
 * - 通道 → 通道、模型、概览、审计
 * - 套餐 → 套餐、概览、审计
 *
 * 用整组前缀而不是在组件里各写各的,删掉一条路由或改一个名字时不会漏刷另一张表。
 */
export const adminInvalidation = {
  all: [queryKeys.admin()],
  user: [queryKeys.adminUsers(), queryKeys.adminOverview(), queryKeys.adminAudit()],
  model: [queryKeys.adminModels(), queryKeys.adminOverview(), queryKeys.adminAudit()],
  provider: [
    queryKeys.adminProviders(),
    queryKeys.adminChannels(),
    queryKeys.adminModels(),
    queryKeys.adminOverview(),
    queryKeys.adminAudit(),
  ],
  channel: [queryKeys.adminChannels(), queryKeys.adminModels(), queryKeys.adminOverview(), queryKeys.adminAudit()],
  plan: [queryKeys.adminPlans(), queryKeys.adminOverview(), queryKeys.adminAudit()],
} as const satisfies Record<string, readonly (readonly unknown[])[]>;

export function useAdminOverview() {
  return useQuery({ queryKey: queryKeys.adminOverview(), queryFn: cloudAdmin.overview });
}

export function useAdminUsers() {
  return useQuery({ queryKey: queryKeys.adminUsers(), queryFn: async () => (await cloudAdmin.users()).users });
}

export function useAdminModels() {
  return useQuery({ queryKey: queryKeys.adminModels(), queryFn: async () => (await cloudAdmin.models()).models });
}

export function useAdminProviders() {
  return useQuery({
    queryKey: queryKeys.adminProviders(),
    queryFn: async () => (await cloudAdmin.providers()).providers,
  });
}

export function useAdminChannels() {
  return useQuery({
    queryKey: queryKeys.adminChannels(),
    queryFn: async () => (await cloudAdmin.channels()).channels,
  });
}

export function useAdminPlans() {
  return useQuery({ queryKey: queryKeys.adminPlans(), queryFn: async () => (await cloudAdmin.plans()).plans });
}

export function useAdminOrders() {
  return useQuery({ queryKey: queryKeys.adminOrders(), queryFn: async () => (await cloudAdmin.orders()).orders });
}

export function useAdminUsage(days = 7) {
  return useQuery({ queryKey: queryKeys.adminUsage(days), queryFn: () => cloudAdmin.usage(days) });
}

export function useAdminAudit() {
  return useQuery({ queryKey: queryKeys.adminAudit(), queryFn: async () => (await cloudAdmin.audit()).events });
}
