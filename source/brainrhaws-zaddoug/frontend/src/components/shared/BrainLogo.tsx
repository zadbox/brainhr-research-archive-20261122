interface BrainLogoProps {
  className?: string;
}

/** Official B monogram, framed to its transparent bounds without redrawing it. */
export function BrainLogo({ className = '' }: BrainLogoProps) {
  return (
    <svg
      role="img"
      aria-label="BRAIN"
      viewBox="171 79 737 922"
      width="737"
      height="922"
      className={`block h-auto ${className}`}
    >
      <image href="/brain-b-dark.png" width="1080" height="1080" className="dark:hidden" />
      <image href="/brain-b-light.png" width="1080" height="1080" className="hidden dark:block" />
    </svg>
  );
}
