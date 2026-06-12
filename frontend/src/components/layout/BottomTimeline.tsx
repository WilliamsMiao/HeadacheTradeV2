import type { TradePlanDetail } from '../../types/api';

interface BottomTimelineProps {
  detail: TradePlanDetail | null;
}

export function BottomTimeline({ detail }: BottomTimelineProps) {
  const events = detail?.audit_timeline.slice(0, 5) ?? [];
  return (
    <footer className="bottom-timeline">
      <div className="section-heading">
        <div>
          <h2>最近系统动作</h2>
          <p>{detail ? `${detail.trade_plan.symbol} 的计划校验与执行记录` : '选择计划后显示相关记录'}</p>
        </div>
      </div>
      <div className="timeline-strip">
        {events.length === 0 ? (
          <span className="timeline-empty">暂无相关系统动作</span>
        ) : (
          events.map((event) => (
            <div className="timeline-event" key={String(event.id)}>
              <time>{event.time ? new Date(String(event.time)).toLocaleTimeString('zh-CN', { hour12: false }) : '—'}</time>
              <strong>{String(event.title || event.type || '系统动作')}</strong>
              <span>{String(event.description || '')}</span>
            </div>
          ))
        )}
      </div>
    </footer>
  );
}
