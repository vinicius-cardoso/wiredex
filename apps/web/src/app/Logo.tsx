export function Logo() {
  return (
    <svg width="22" height="22" viewBox="0 0 18 18" aria-hidden="true" className="text-primary">
      <rect
        x="3"
        y="3"
        width="12"
        height="12"
        rx="2"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="M6 .5V3M9 .5V3M12 .5V3M6 15v2.5M9 15v2.5M12 15v2.5M.5 6H3M.5 12H3M15 6h2.5M15 12h2.5"
        stroke="currentColor"
        strokeWidth="1.4"
      />
      <circle cx="7" cy="7" r="1.3" fill="currentColor" />
    </svg>
  );
}
