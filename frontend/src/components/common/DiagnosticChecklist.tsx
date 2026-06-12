import { CheckCircleFilled, ClockCircleFilled, CloseCircleFilled } from '@ant-design/icons';
import type { DiagnosticCheck } from '../../types/api';

interface DiagnosticChecklistProps {
  checks: DiagnosticCheck[];
}

export function DiagnosticChecklist({ checks }: DiagnosticChecklistProps) {
  return (
    <div className="diagnostic-list">
      {checks.map((check) => {
        const Icon =
          check.passed === true
            ? CheckCircleFilled
            : check.passed === false
              ? CloseCircleFilled
              : ClockCircleFilled;
        const state = check.passed === true ? 'pass' : check.passed === false ? 'fail' : 'pending';
        return (
          <div className={`diagnostic-item diagnostic-item--${state}`} key={check.label}>
            <Icon aria-hidden />
            <div>
              <strong>{check.label}</strong>
              <span>{check.detail}</span>
            </div>
            <b>{check.result}</b>
          </div>
        );
      })}
    </div>
  );
}
