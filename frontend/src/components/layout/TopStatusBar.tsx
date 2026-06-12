import { Button } from 'antd';
import { ArrowLeftOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import type { ApiMeta, TerminalSummary } from '../../types/api';
import { MetricCard } from '../common/MetricCard';

interface TopStatusBarProps {
  summary: TerminalSummary;
  meta: ApiMeta;
}

const money = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

export function TopStatusBar({ summary, meta }: TopStatusBarProps) {
  const syncedAt = summary.account_equity_synced_at
    ? new Date(summary.account_equity_synced_at).toLocaleString('zh-CN', { hour12: false })
    : '尚未同步';
  return (
    <header className="terminal-header">
      <div className="terminal-header__identity">
        <Button
          aria-label="返回稳定后台"
          href="/"
          icon={<ArrowLeftOutlined />}
          type="text"
        />
        <div>
          <h1>HeadacheTrade 交易终端</h1>
          <p>只读模拟交易工作台</p>
        </div>
      </div>
      <div className="terminal-metrics">
        <MetricCard
          title="交易模式"
          value="模拟交易"
          description="真实交易永久关闭"
          tone="success"
        />
        <MetricCard
          title="Futu 连接"
          value={summary.futu_trade_status === 'OK' ? '已连接' : '待确认'}
          description={`权益同步：${syncedAt}`}
          tone={summary.futu_trade_status === 'OK' ? 'success' : 'warning'}
        />
        <MetricCard
          title="模拟账户权益"
          value={money.format(summary.account_equity)}
          description={meta.source === 'FUTU_SIM_ACCOUNT' ? '来自 Futu 模拟账户' : '资金来源未确认'}
          tone={summary.account_equity_sync_status === 'OK' ? 'neutral' : 'danger'}
        />
        <MetricCard
          title="当前持仓"
          value={`${summary.positions_count} / ${summary.max_positions}`}
          description={summary.can_open_new_position ? '风控允许继续评估新仓' : '当前禁止新增仓位'}
          tone={summary.can_open_new_position ? 'neutral' : 'warning'}
        />
      </div>
      <div className="terminal-safety">
        <SafetyCertificateOutlined aria-hidden />
        <span>REAL TRADING DISABLED</span>
      </div>
    </header>
  );
}
