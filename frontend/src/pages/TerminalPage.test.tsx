import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TerminalPage } from './TerminalPage';

const summary = {
  data: {
    mode: 'SIM_TRADING',
    real_trading: 'DISABLED',
    sim_loop_status: 'OK',
    futu_quote_status: 'OK',
    futu_trade_status: 'OK',
    account_equity: 1000000,
    account_equity_source: 'FUTU_SIM_ACCOUNT',
    account_equity_sync_status: 'OK',
    account_equity_synced_at: '2026-06-12T06:00:00+00:00',
    today_pnl: 0,
    today_realized_r: 0,
    positions_count: 0,
    max_positions: 1,
    can_open_new_position: true,
    risk_stop_reason: null,
  },
  meta: { synced_at: '2026-06-12T06:00:00+00:00', source: 'FUTU_SIM_ACCOUNT', stale: false },
};

const plan = {
  id: 1,
  symbol: 'US.AAPL',
  name: 'Apple',
  priority_level: 'S',
  direction: 'LONG',
  structure_type: 'BOTTOM_STRUCTURE',
  structure_display_name: '底结构',
  status: 'ACTIVE',
  display_status: {
    code: 'ACTIVE',
    display_name: '持续监控中',
    description: '计划有效',
    severity: 'info',
    next_action: '继续监控',
  },
  current_price: 181,
  current_change_pct: 1,
  entry_price: 180,
  no_chase_above: 182,
  stop_price: 175,
  target_1: 187.5,
  target_2: 190,
  risk_reward_1: 1.5,
  risk_reward_2: 2,
  capital_status: 'CAPITAL_AVAILABLE',
  capital_display_name: '资金可用',
  rules_approval_status: 'NOT_REVIEWED',
  rules_approval_display_name: '尚未审核',
  primary_blocker: null,
  primary_blocker_reason: null,
  next_system_action: '继续监控价格。',
  price_gate_status: '价格条件已满足',
  validation_status: '等待实时确认',
  checks: [],
  reason: '结构确认',
  trailing_rule: '逐步抬高止损',
  time_stop_rule: '三根 K 线未走强则失效',
  invalid_condition: '跌破结构低点',
  last_validated_at: null,
  updated_at: '2026-06-12T06:00:00+00:00',
};

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === '/api/terminal/summary') return Response.json(summary);
      if (path.startsWith('/api/trade-plans?')) {
        return Response.json({ data: [plan], meta: summary.meta });
      }
      if (path === '/api/trade-plans/1') {
        return Response.json({
          data: {
            candidate: null,
            structure_event: null,
            battle_item: null,
            trade_plan: plan,
            realtime_checks: [],
            rules_approval_checks: { status: 'NOT_REVIEWED', display_name: '尚未审核', reason: '' },
            capital_checks: {
              status: 'CAPITAL_AVAILABLE',
              display_name: '资金可用',
              reason: '',
              available_cash_snapshot: 800000,
              max_new_position_value: 400000,
            },
            related_orders: [],
            related_position: null,
            journal_summary: null,
            audit_timeline: [],
          },
          meta: summary.meta,
        });
      }
      if (path.startsWith('/api/kline?')) {
        return Response.json({
          data: [],
          meta: summary.meta,
          context: { symbol: 'US.AAPL', timeframe: '60m', anomaly_count: 0 },
        });
      }
      if (path.startsWith('/api/trade-plan-overlays?')) {
        return Response.json({
          data: { symbol: 'US.AAPL', plan_id: 1, lines: [] },
          meta: summary.meta,
        });
      }
      if (path.startsWith('/api/structures?')) {
        return Response.json({ data: [], meta: summary.meta });
      }
      return Response.json({ data: [], meta: summary.meta });
    }),
  );
});

describe('TerminalPage', () => {
  it('renders simulation safety state and selected S plan detail', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <TerminalPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText('模拟交易')).toBeInTheDocument();
    expect(screen.getByText('REAL TRADING DISABLED')).toBeInTheDocument();
    expect(await screen.findByText('AAPL 行情')).toBeInTheDocument();
    expect(await screen.findByText('当前没有 60 分钟 K 线数据')).toBeInTheDocument();
    expect(await screen.findByText('图中结构事件')).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText('持续监控中').length).toBeGreaterThan(0));
  });
});
