import { Segmented } from 'antd';
import type { TradePlan } from '../../types/api';
import { useTerminalStore } from '../../store/terminalStore';

interface PriceFrameworkProps {
  plan: TradePlan;
}

const price = (value: number | null) => (value == null ? '—' : value.toFixed(2));

export function PriceFramework({ plan }: PriceFrameworkProps) {
  const timeframe = useTerminalStore((state) => state.selectedTimeframe);
  const setTimeframe = useTerminalStore((state) => state.setTimeframe);
  return (
    <section className="price-workspace">
      <div className="section-heading">
        <div>
          <h2>{plan.symbol.replace('US.', '')} 价格框架</h2>
          <p>{plan.structure_display_name} · {plan.direction === 'LONG' ? '做多观察' : '风险观察'}</p>
        </div>
        <Segmented
          aria-label="选择时间周期"
          onChange={(value) => setTimeframe(value as '60m' | '1d')}
          options={[
            { label: '60 分钟', value: '60m' },
            { label: '日线', value: '1d' },
          ]}
          value={timeframe}
        />
      </div>
      <div className="price-canvas" aria-label={`${timeframe} 价格框架`}>
        <div className="price-canvas__range">
          <span className="price-line price-line--target">目标二 <b>{price(plan.target_2)}</b></span>
          <span className="price-line price-line--target">目标一 <b>{price(plan.target_1)}</b></span>
          <span className="price-line price-line--no-chase">最高可接受价 <b>{price(plan.no_chase_above)}</b></span>
          <span className="price-line price-line--current">当前价 <b>{price(plan.current_price)}</b></span>
          <span className="price-line price-line--entry">计划入场价 <b>{price(plan.entry_price)}</b></span>
          <span className="price-line price-line--stop">硬止损价 <b>{price(plan.stop_price)}</b></span>
        </div>
      </div>
      <div className="price-summary">
        <div><span>第一目标风险收益比</span><strong>{plan.risk_reward_1.toFixed(2)}R</strong></div>
        <div><span>第二目标风险收益比</span><strong>{plan.risk_reward_2.toFixed(2)}R</strong></div>
        <div><span>最近实时确认</span><strong>{plan.last_validated_at ? new Date(plan.last_validated_at).toLocaleString('zh-CN', { hour12: false }) : '尚未确认'}</strong></div>
      </div>
    </section>
  );
}
