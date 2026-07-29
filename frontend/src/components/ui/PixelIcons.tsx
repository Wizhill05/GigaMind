import React from 'react';

interface PixelIconProps {
  className?: string;
  size?: number;
}

export const PixelBrain: React.FC<PixelIconProps> = ({ className = "w-4 h-4 text-[#ff6b00]", size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="currentColor" className={className}>
    {/* 8-bit Pixel Brain */}
    <rect x="4" y="2" width="8" height="2" />
    <rect x="2" y="4" width="12" height="2" />
    <rect x="2" y="6" width="5" height="4" />
    <rect x="9" y="6" width="5" height="4" />
    <rect x="3" y="10" width="10" height="2" />
    <rect x="5" y="12" width="6" height="2" />
  </svg>
);

export const PixelDatabase: React.FC<PixelIconProps> = ({ className = "w-4 h-4 text-[#ff6b00]", size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="currentColor" className={className}>
    {/* 8-bit Pixel Database / Disk */}
    <rect x="3" y="2" width="10" height="2" />
    <rect x="2" y="4" width="12" height="2" />
    <rect x="3" y="7" width="10" height="2" />
    <rect x="2" y="9" width="12" height="2" />
    <rect x="3" y="12" width="10" height="2" />
  </svg>
);

export const PixelShield: React.FC<PixelIconProps> = ({ className = "w-4 h-4 text-[#ff6b00]", size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="currentColor" className={className}>
    {/* 8-bit Pixel Shield */}
    <rect x="2" y="2" width="12" height="2" />
    <rect x="2" y="4" width="12" height="4" />
    <rect x="3" y="8" width="10" height="3" />
    <rect x="5" y="11" width="6" height="2" />
    <rect x="7" y="13" width="2" height="2" />
  </svg>
);

export const PixelTerminal: React.FC<PixelIconProps> = ({ className = "w-4 h-4 text-[#ff6b00]", size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="currentColor" className={className}>
    {/* 8-bit Pixel Terminal */}
    <rect x="2" y="2" width="12" height="10" />
    <rect x="4" y="4" width="2" height="2" fill="#0a0b0e" />
    <rect x="6" y="6" width="2" height="2" fill="#0a0b0e" />
    <rect x="4" y="8" width="2" height="2" fill="#0a0b0e" />
    <rect x="9" y="8" width="3" height="2" fill="#0a0b0e" />
    <rect x="6" y="13" width="4" height="2" />
  </svg>
);

export const PixelSparkles: React.FC<PixelIconProps> = ({ className = "w-4 h-4 text-[#ff6b00]", size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="currentColor" className={className}>
    {/* 8-bit Pixel Sparkles / Pixel Star */}
    <rect x="7" y="1" width="2" height="14" />
    <rect x="1" y="7" width="14" height="2" />
    <rect x="5" y="5" width="6" height="6" />
    <rect x="3" y="3" width="2" height="2" />
    <rect x="11" y="3" width="2" height="2" />
    <rect x="3" y="11" width="2" height="2" />
    <rect x="11" y="11" width="2" height="2" />
  </svg>
);

export const PixelSettings: React.FC<PixelIconProps> = ({ className = "w-4 h-4 text-[#ff6b00]", size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="currentColor" className={className}>
    {/* 8-bit Pixel Gear */}
    <rect x="6" y="1" width="4" height="14" />
    <rect x="1" y="6" width="14" height="4" />
    <rect x="4" y="4" width="8" height="8" />
    <rect x="6" y="6" width="4" height="4" fill="#0a0b0e" />
  </svg>
);

export const PixelKey: React.FC<PixelIconProps> = ({ className = "w-4 h-4 text-[#ff6b00]", size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="currentColor" className={className}>
    {/* 8-bit Pixel Key */}
    <rect x="2" y="2" width="6" height="6" />
    <rect x="4" y="4" width="2" height="2" fill="#0a0b0e" />
    <rect x="7" y="4" width="7" height="2" />
    <rect x="10" y="6" width="2" height="2" />
    <rect x="13" y="6" width="1" height="2" />
  </svg>
);

export const PixelGlobe: React.FC<PixelIconProps> = ({ className = "w-4 h-4 text-[#ff6b00]", size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="currentColor" className={className}>
    {/* 8-bit Pixel Globe */}
    <rect x="4" y="1" width="8" height="14" />
    <rect x="1" y="4" width="14" height="8" />
    <rect x="7" y="1" width="2" height="14" fill="#0a0b0e" />
    <rect x="1" y="7" width="14" height="2" fill="#0a0b0e" />
  </svg>
);
