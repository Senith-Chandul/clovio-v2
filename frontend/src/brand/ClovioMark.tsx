type ClovioMarkProps = {
  className?: string;
  /** About 9 at 24px or smaller, so the orbits don't break up. */
  strokeWidth?: number;
};

export default function ClovioMark({ className = 'h-6 w-6', strokeWidth = 4.75 }: ClovioMarkProps) {
  return (
    <svg viewBox="0 0 128 128" className={className} fill="none" aria-hidden="true">
      <path
        d="M64 12L74 46L110 56L74 66L64 116L54 66L18 56L54 46L64 12Z"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <ellipse cx="64" cy="64" rx="46" ry="18" transform="rotate(34 64 64)" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" />
      <ellipse cx="64" cy="64" rx="46" ry="18" transform="rotate(-34 64 64)" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" />
    </svg>
  );
}
