export const platformRoleLabels = {
  ADMIN: '管理员',
  TEST: '测试',
  DEV: '开发',
  PRODUCT: '产品',
  MANAGER: '经理',
  USER: '普通用户',
} as const;

export type PlatformRole = keyof typeof platformRoleLabels;
