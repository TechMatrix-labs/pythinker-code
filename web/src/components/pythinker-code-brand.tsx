import { pythinkerCliVersion } from "@/lib/version";
import { pythinkerBrand } from "@/lib/brand";
import { cn } from "@/lib/utils";

type PythinkerCodeBrandProps = {
  className?: string;
  size?: "sm" | "md";
  showVersion?: boolean;
};

export function PythinkerCodeBrand({
  className,
  size = "md",
  showVersion = true,
}: PythinkerCodeBrandProps) {
  const textSizeClass = size === "sm" ? "text-base" : "text-lg";
  const versionPadding = size === "sm" ? "text-xs" : "text-sm";
  const logoSize = size === "sm" ? "size-6" : "size-7";
  const logoPx = size === "sm" ? 24 : 28;

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <a
        href={pythinkerBrand.homepageUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-center gap-2 hover:opacity-80 transition-opacity"
      >
        <img
          src={pythinkerBrand.logoSrc}
          alt={pythinkerBrand.logoAlt}
          width={logoPx}
          height={logoPx}
          className={logoSize}
        />
        <span className={cn(textSizeClass, "font-semibold text-foreground")}>
          {pythinkerBrand.productName}
        </span>
      </a>
      {showVersion && (
        <span
          className={cn("text-muted-foreground font-medium", versionPadding)}
        >
          v{pythinkerCliVersion}
        </span>
      )}
    </div>
  );
}
