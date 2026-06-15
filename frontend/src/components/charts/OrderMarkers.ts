import type { ExecutionMarker, SimOrder } from '../../types/api';
import { tradingColors } from '../../theme/tradingColors';

export function buildOrderMarkers(orders: SimOrder[]): ExecutionMarker[] {
  return orders.flatMap((order) => {
    if (!order.filled_at || order.filled_price === null || order.filled_qty <= 0) return [];
    const isBuy = order.side.toUpperCase() === 'BUY';
    const time = Math.floor(new Date(order.filled_at).getTime() / 1000);
    if (!Number.isFinite(time)) return [];
    return [{
      id: `order-${order.id}`,
      time,
      price: order.filled_price,
      position: isBuy ? 'belowBar' : 'aboveBar',
      shape: isBuy ? 'arrowUp' : 'arrowDown',
      color: isBuy ? tradingColors.filled : tradingColors.danger,
      text: isBuy ? `买入成交 ${order.filled_qty} 股` : `卖出成交 ${order.filled_qty} 股`,
    }];
  });
}
