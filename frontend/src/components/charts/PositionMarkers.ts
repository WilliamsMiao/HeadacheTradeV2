import type { ExecutionMarker, Position } from '../../types/api';
import { tradingColors } from '../../theme/tradingColors';

export function buildPositionMarkers(
  positions: Position[],
  filledOrderIds: Set<number>,
): ExecutionMarker[] {
  return positions.flatMap((position) => {
    const markers: ExecutionMarker[] = [];
    const entryTime = Math.floor(new Date(position.created_at).getTime() / 1000);
    if (
      Number.isFinite(entryTime)
      && (!position.entry_order_id || !filledOrderIds.has(position.entry_order_id))
    ) {
      markers.push({
        id: `position-entry-${position.id}`,
        time: entryTime,
        price: position.entry_price,
        position: 'belowBar',
        shape: 'circle',
        color: tradingColors.filled,
        text: `建立持仓 ${position.shares} 股`,
      });
    }
    if (
      position.status !== 'OPEN'
      && position.current_price !== null
      && Number.isFinite(new Date(position.updated_at).getTime())
      && (!position.exit_order_id || !filledOrderIds.has(position.exit_order_id))
    ) {
      markers.push({
        id: `position-exit-${position.id}`,
        time: Math.floor(new Date(position.updated_at).getTime() / 1000),
        price: position.current_price,
        position: 'aboveBar',
        shape: 'square',
        color: position.current_r >= 0 ? tradingColors.filled : tradingColors.danger,
        text: position.exit_reason || '持仓已结束',
      });
    }
    return markers;
  });
}
