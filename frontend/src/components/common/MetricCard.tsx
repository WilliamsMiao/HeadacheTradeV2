import type { ReactNode } from 'react';

interface MetricCardProps {
  title: string;
  value: ReactNode;
  description: string;
  tone?: 'success' | 'warning' | 'danger' | 'neutral';
}

export function MetricCard({ title, value, description, tone = 'neutral' }: MetricCardProps) {
  return (
    <section className={`metric-card metric-card--${tone}`}>
      <span className="metric-card__title">{title}</span>
      <strong className="metric-card__value">{value}</strong>
      <span className="metric-card__description">{description}</span>
    </section>
  );
}
