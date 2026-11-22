/** Design-system progress ring: primary on a primary-soft track, the percentage in the middle. */
export default function Ring({ percent, label }: { percent: number; label?: string }) {
  const value = Math.max(0, Math.min(100, Math.round(percent)));
  const circumference = 2 * Math.PI * 19;
  return (
    <span className="clv-ring" role="img" aria-label={label ?? `${value}%`}>
      <svg width="46" height="46" viewBox="0 0 46 46" aria-hidden="true">
        <circle className="clv-track" cx="23" cy="23" r="19" strokeWidth="5" />
        <circle
          className="clv-value" cx="23" cy="23" r="19" strokeWidth="5" strokeLinecap="round"
          strokeDasharray={`${(value / 100) * circumference} ${circumference}`}
          transform="rotate(-90 23 23)"
        />
      </svg>
      <span className="clv-ring-label">{value}%</span>
    </span>
  );
}
