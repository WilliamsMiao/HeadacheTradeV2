import { EmptyState } from '../common/EmptyState';
import { StatusBadge } from '../common/StatusBadge';
import type { TradePlan } from '../../types/api';

interface SymbolPlanListProps {
  plans: TradePlan[];
  selectedId: number | null;
  onSelect: (plan: TradePlan) => void;
}

const price = (value: number | null) => (value == null ? '—' : value.toFixed(2));

export function SymbolPlanList({ plans, selectedId, onSelect }: SymbolPlanListProps) {
  if (plans.length === 0) {
    return <EmptyState description="当前没有 S/A 级监控计划" />;
  }
  return (
    <div className="plan-list">
      {plans.map((plan) => (
        <button
          className={`plan-list-item${selectedId === plan.id ? ' is-selected' : ''}`}
          key={plan.id}
          onClick={() => onSelect(plan)}
          type="button"
        >
          <div className="plan-list-item__heading">
            <span className={`priority priority--${plan.priority_level.toLowerCase()}`}>
              {plan.priority_level}
            </span>
            <strong>{plan.symbol.replace('US.', '')}</strong>
            <StatusBadge status={plan.status} label={plan.display_status.display_name} />
          </div>
          <span className="plan-list-item__name">{plan.name || plan.structure_display_name}</span>
          <div className="plan-list-item__prices">
            <span>现价 <b>{price(plan.current_price)}</b></span>
            <span>入场 <b>{price(plan.entry_price)}</b></span>
            <span>止损 <b>{price(plan.stop_price)}</b></span>
          </div>
          <p>{plan.primary_blocker_reason || plan.next_system_action}</p>
        </button>
      ))}
    </div>
  );
}
