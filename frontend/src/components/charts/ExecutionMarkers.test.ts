import { describe, expect, it } from 'vitest';

import type { Position, SimOrder } from '../../types/api';
import { buildOrderMarkers } from './OrderMarkers';
import { buildPositionMarkers } from './PositionMarkers';

const order: SimOrder = {
  id: 11,
  trade_plan_id: 1,
  symbol: 'US.AAPL',
  side: 'BUY',
  qty: 100,
  limit_price: 180,
  filled_price: 180.2,
  filled_qty: 100,
  status: 'FILLED',
  display_status: {
    code: 'FILLED',
    display_name: '已成交',
    description: '',
    severity: 'success',
    next_action: '',
  },
  submitted_at: '2026-06-12T14:30:00Z',
  filled_at: '2026-06-12T14:31:00Z',
  reason: '',
};

const position: Position = {
  id: 21,
  symbol: 'US.AAPL',
  direction: 'LONG',
  status: 'OPEN',
  entry_price: 180.2,
  current_price: 181,
  current_r: 0.16,
  max_r: 0.2,
  min_r: -0.1,
  stop_price: 175,
  target_1: 187.5,
  target_2: 190,
  partial_exit_done: false,
  trailing_stop_price: null,
  next_system_action: '继续持有',
  exit_reason: '',
  source_trade_plan_id: 1,
  entry_order_id: 11,
  exit_order_id: null,
  shares: 100,
  created_at: '2026-06-12T14:31:00Z',
  updated_at: '2026-06-12T14:35:00Z',
};

describe('execution chart markers', () => {
  it('creates a buy marker only after an order is filled', () => {
    expect(buildOrderMarkers([order])).toEqual([
      expect.objectContaining({
        id: 'order-11',
        price: 180.2,
        position: 'belowBar',
        text: '买入成交 100 股',
      }),
    ]);
    expect(buildOrderMarkers([{ ...order, filled_at: null, filled_qty: 0 }])).toEqual([]);
    expect(buildOrderMarkers([{ ...order, filled_at: 'invalid' }])).toEqual([]);
  });

  it('does not duplicate a position entry already represented by its filled order', () => {
    expect(buildPositionMarkers([position], new Set([11]))).toEqual([]);
    expect(buildPositionMarkers([{ ...position, entry_order_id: null }], new Set())).toEqual([
      expect.objectContaining({ id: 'position-entry-21', text: '建立持仓 100 股' }),
    ]);
  });

  it('marks a closed position when no filled exit order represents it', () => {
    const markers = buildPositionMarkers([
      {
        ...position,
        status: 'CLOSED',
        current_r: -1,
        current_price: 175,
        exit_reason: '触发硬止损',
      },
    ], new Set([11]));

    expect(markers).toEqual([
      expect.objectContaining({
        id: 'position-exit-21',
        price: 175,
        text: '触发硬止损',
      }),
    ]);
  });
});
