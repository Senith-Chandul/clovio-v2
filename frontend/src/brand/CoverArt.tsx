/** The design system's cover: an indigo slab with satellites, and two sets of bars. */
export default function CoverArt({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 480 288" className={className} aria-hidden="true" focusable="false">
      <rect x="16" y="-16" width="176" height="232" rx="22" fill="var(--primary)" />
      <rect x="208" y="24" width="160" height="56" rx="22" fill="var(--primary-soft)" />
      <rect x="208" y="96" width="160" height="168" rx="22" fill="var(--inverse)" />
      <rect x="384" y="48" width="192" height="216" rx="22" fill="var(--secondary)" />
      {[[228, 168, 72], [252, 184, 56], [276, 208, 32], [300, 192, 48], [324, 216, 24]].map(([x, y, h]) => (
        <rect key={x} x={x} y={y} width="16" height={h} rx="8" fill="var(--primary-soft)" />
      ))}
      {[392, 416, 440, 464].map((x) => (
        <rect key={x} x={x} y="184" width="16" height="56" rx="8" fill="var(--ground)" />
      ))}
    </svg>
  );
}
