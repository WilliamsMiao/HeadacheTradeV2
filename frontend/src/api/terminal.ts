import { apiGet } from './client';
import type { Position, SimOrder, TerminalSummary, TradePlan, TradePlanDetail } from '../types/api';

export const getTerminalSummary = () => apiGet<TerminalSummary>('/api/terminal/summary');

export const getTradePlans = () =>
  apiGet<TradePlan[]>('/api/trade-plans?active_only=true&priority=S,A');

export const getTradePlanDetail = (id: number) =>
  apiGet<TradePlanDetail>(`/api/trade-plans/${id}`);

export const getPositions = () => apiGet<Position[]>('/api/positions');

export const getOrders = () => apiGet<SimOrder[]>('/api/sim-orders');
