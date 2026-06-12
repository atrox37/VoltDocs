import type { CSSProperties } from 'react';
import { APP_ICON } from '@/constants/assets';

interface BrandIconProps {
  size?: number;
  className?: string;
  style?: CSSProperties;
}

export default function BrandIcon({ size = 32, className, style }: BrandIconProps) {
  return (
    <img
      src={APP_ICON}
      alt="VoltDocs"
      width={size}
      height={size}
      className={className}
      style={{ borderRadius: 6, ...style }}
    />
  );
}
