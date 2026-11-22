import type { ReactNode } from 'react';

const ARC = 'M 20 100 A 80 80 0 0 1 180 100';
const ARC_LENGTH = 251.3;

interface GaugeProps {
  /** Share of the arc to fill, 0–1. */
  fraction: number;
  /** The number printed in the middle. */
  value: ReactNode;
  caption: string;
  label: string;
}

/** Design-system semicircle gauge: one number against a total, one per card. */
export default function Gauge({ fraction, value, caption, label }: GaugeProps) {
  return (
    <div className="clv-gauge mx-auto" role="img" aria-label={label}>
      <svg width="200" height="112" viewBox="0 0 200 112" aria-hidden="true">
        <path className="clv-track" d={ARC} strokeWidth="22" strokeLinecap="round" />
        <path
          className="clv-value" d={ARC} strokeWidth="22" strokeLinecap="round"
          strokeDasharray={`${Math.max(0, Math.min(1, fraction)) * ARC_LENGTH} 300`}
        />
      </svg>
      <div className="clv-gauge-label">
        <div className="clv-gauge-number">{value}</div>
        <div className="clv-gauge-caption">{caption}</div>
      </div>
    </div>
  );
}
