import { tradingBackgrounds, tradingColors } from './tradingColors';

export type StatusTone =
  | 'armed'
  | 'triggered'
  | 'noChase'
  | 'invalidated'
  | 'waitlist'
  | 'filled'
  | 'danger'
  | 'neutral';

const toneByStatus: Record<string, StatusTone> = {
  ACTIVE: 'armed',
  ARMED: 'armed',
  PLANNED: 'neutral',
  TRIGGERED: 'triggered',
  ORDER_SUBMITTED: 'triggered',
  IN_POSITION: 'filled',
  FILLED: 'filled',
  NO_CHASE: 'noChase',
  WAIT_PULLBACK: 'waitlist',
  WAITLIST: 'waitlist',
  MISSED_BY_CAPITAL: 'waitlist',
  BLOCKED: 'danger',
  PAUSED: 'waitlist',
  INVALIDATED: 'invalidated',
  EXPIRED: 'neutral',
};

export function statusVisual(status: string) {
  const tone = toneByStatus[status] ?? 'neutral';
  return {
    tone,
    color: tradingColors[tone],
    background: tradingBackgrounds[tone],
  };
}
