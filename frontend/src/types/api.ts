export interface ApiMeta {
  synced_at: string;
  source: string;
  stale: boolean;
}

export interface ApiEnvelope<T> {
  data: T;
  meta: ApiMeta;
  context?: Record<string, unknown>;
}

export type Timeframe = '1m' | '5m' | '15m' | '60m' | '1d';

export interface KlineBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TradePlanOverlayLine {
  type: 'ENTRY' | 'NO_CHASE' | 'STOP' | 'TARGET_1' | 'TARGET_2' | 'CURRENT';
  label: string;
  price: number;
}

export interface TradePlanOverlay {
  symbol: string;
  plan_id: number | null;
  lines: TradePlanOverlayLine[];
}

export interface StructureMarker {
  id: number;
  symbol: string;
  timeframe: string;
  event_ts: string;
  event_type: string;
  display_name: string;
  price: number;
  pivot_low: number | null;
  pivot_high: number | null;
  trigger_level: number | null;
  confirm_level: number | null;
  invalidation_level: number | null;
  reason: string;
  linked_battle_item_id: number | null;
  linked_trade_plan_id: number | null;
}

export interface ExecutionMarker {
  id: string;
  time: number;
  price: number;
  position: 'aboveBar' | 'belowBar';
  shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square';
  color: string;
  text: string;
}

export interface StatusPresentation {
  code: string;
  display_name: string;
  description: string;
  severity: string;
  next_action: string;
}

export interface TerminalSummary {
  mode: string;
  real_trading: string;
  sim_loop_status: string;
  futu_quote_status: string;
  futu_trade_status: string;
  account_equity: number;
  account_equity_source: string;
  account_equity_sync_status: string;
  account_equity_synced_at: string | null;
  today_pnl: number;
  today_realized_r: number;
  positions_count: number;
  max_positions: number;
  can_open_new_position: boolean;
  risk_stop_reason: string | null;
}

export interface DiagnosticCheck {
  label: string;
  passed: boolean | null;
  result: string;
  detail: string;
  block_message: string;
}

export interface TradePlan {
  id: number;
  symbol: string;
  name: string;
  priority_level: string;
  direction: string;
  structure_type: string;
  structure_display_name: string;
  status: string;
  display_status: StatusPresentation;
  current_price: number | null;
  current_change_pct: number | null;
  entry_price: number | null;
  no_chase_above: number | null;
  stop_price: number;
  target_1: number;
  target_2: number;
  risk_reward_1: number;
  risk_reward_2: number;
  capital_status: string;
  capital_display_name: string;
  rules_approval_status: string;
  rules_approval_display_name: string;
  primary_blocker: string | null;
  primary_blocker_reason: string | null;
  next_system_action: string;
  price_gate_status: string;
  validation_status: string;
  checks: DiagnosticCheck[];
  reason: string;
  trailing_rule: string;
  time_stop_rule: string;
  invalid_condition: string;
  last_validated_at: string | null;
  updated_at: string;
}

export interface TradePlanDetail {
  candidate: Record<string, unknown> | null;
  structure_event: Record<string, unknown> | null;
  battle_item: Record<string, unknown> | null;
  trade_plan: TradePlan;
  realtime_checks: DiagnosticCheck[];
  rules_approval_checks: {
    status: string;
    display_name: string;
    reason: string;
  };
  capital_checks: {
    status: string;
    display_name: string;
    reason: string;
    available_cash_snapshot: number | null;
    max_new_position_value: number | null;
  };
  related_orders: SimOrder[];
  related_position: Position | null;
  journal_summary: Record<string, unknown> | null;
  audit_timeline: Array<Record<string, unknown>>;
}

export interface Position {
  id: number;
  symbol: string;
  direction: string;
  status: string;
  entry_price: number;
  current_price: number | null;
  current_r: number;
  max_r: number;
  min_r: number;
  stop_price: number;
  target_1: number | null;
  target_2: number | null;
  partial_exit_done: boolean;
  trailing_stop_price: number | null;
  next_system_action: string;
  exit_reason: string;
  source_trade_plan_id: number | null;
  entry_order_id: number | null;
  exit_order_id: number | null;
  shares: number;
  created_at: string;
  updated_at: string;
}

export interface SimOrder {
  id: number;
  trade_plan_id: number | null;
  symbol: string;
  side: string;
  qty: number;
  limit_price: number;
  filled_price: number | null;
  filled_qty: number;
  status: string;
  display_status: StatusPresentation;
  submitted_at: string;
  filled_at: string | null;
  reason: string;
}
