import type { ThemeConfig } from 'antd';

export const shadcnTheme: ThemeConfig = {
  token: {
    colorPrimary: '#262626',
    colorInfo: '#2563eb',
    colorSuccess: '#22c55e',
    colorWarning: '#f97316',
    colorError: '#ef4444',
    colorBgBase: '#ffffff',
    colorBgLayout: '#fafafa',
    colorBgContainer: '#ffffff',
    colorTextBase: '#262626',
    colorTextSecondary: '#737373',
    colorBorder: '#e5e5e5',
    colorBorderSecondary: '#f0f0f0',
    borderRadius: 8,
    borderRadiusLG: 8,
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
    fontSize: 14,
    lineWidth: 1,
    boxShadow: '0 1px 2px rgba(0, 0, 0, 0.04)',
    boxShadowSecondary: '0 4px 12px rgba(0, 0, 0, 0.06)',
  },
  components: {
    Button: {
      controlHeight: 40,
      primaryShadow: 'none',
    },
    Card: {
      headerBg: '#ffffff',
      paddingLG: 20,
    },
    Layout: {
      bodyBg: '#fafafa',
      headerBg: '#ffffff',
      siderBg: '#ffffff',
    },
    Tag: {
      borderRadiusSM: 6,
    },
  },
};
