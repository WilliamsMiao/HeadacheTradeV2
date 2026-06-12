import { apiGet } from './client';
import type {
  KlineBar,
  Position,
  SimOrder,
  TerminalSummary,
  TradePlan,
  TradePlanDetail,
} from '../types/api';

export const getTerminalSummary = () => apiGet<TerminalSummary>('/api/terminal/summary');

export const getTradePlans = () =>
  apiGet<TradePlan[]>('/api/trade-plans?active_only=true&priority=S,A');

export const getTradePlanDetail = (id: number) =>
  apiGet<TradePlanDetail>(`/api/trade-plans/${id}`);

export const getPositions = () => apiGet<Position[]>('/api/positions');

export const getOrders = () => apiGet<SimOrder[]>('/api/sim-orders');

export const getKlines = (symbol: string, timeframe: '60m' | '1d', limit = 300) =>
  apiGet<KlineBar[]>(
    `/api/kline?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&limit=${limit}`,
  );
