export function LogoMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <rect width="64" height="64" rx="14" fill="#2563eb" />
      <path
        d="M10 40 L20 32 L26 36 L34 22 L42 28 L54 18"
        stroke="#fff"
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <circle cx="34" cy="22" r="3.2" fill="#fff" />
    </svg>
  );
}
