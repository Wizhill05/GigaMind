import React from 'react';

interface AgentBadgeProps {
  agent?: string;
}

export const AgentBadge: React.FC<AgentBadgeProps> = ({ agent }) => {
  const normalized = (agent || 'user').toLowerCase();

  let bg = 'bg-[#222222] text-[#c1c5d0] border-[#333333]';
  let label = agent;

  if (normalized.includes('claude')) {
    bg = 'bg-[#ff6b00]/10 text-[#ff6b00] border-[#ff6b00]/30';
    label = 'Claude';
  } else if (normalized.includes('gpt') || normalized.includes('openai')) {
    bg = 'bg-[#f59e0b]/10 text-[#f59e0b] border-[#f59e0b]/30';
    label = 'GPT';
  } else if (normalized.includes('gemini')) {
    bg = 'bg-[#06b6d4]/10 text-[#06b6d4] border-[#06b6d4]/30';
    label = 'Gemini';
  } else if (normalized.includes('user')) {
    bg = 'bg-[#ff8800]/10 text-[#ff8800] border-[#ff8800]/30';
    label = 'User';
  } else if (normalized.includes('system') || normalized.includes('mcp')) {
    bg = 'bg-amber-500/10 text-amber-400 border-amber-500/30';
    label = 'System';
  }

  return (
    <span className={`inline-flex items-center px-2 py-0.5 text-xs font-sans font-medium border rounded-none tracking-wide ${bg}`}>
      {label}
    </span>
  );
};

export const CategoryBadge: React.FC<{ category?: string }> = ({ category }) => {
  return (
    <span className="inline-flex items-center px-2 py-0.5 text-xs font-sans text-[#8a8f9e] bg-[#161616] border border-[#262626] rounded-none">
      {category || 'general'}
    </span>
  );
};

export const RenderPill: React.FC<{ label: string; variant?: 'orange' | 'orangeFilled' | 'amber' | 'gray' }> = ({
  label,
  variant = 'gray',
}) => {
  let styles = 'bg-[#262626] text-[#c1c5d0] border-[#333333]';

  if (variant === 'orangeFilled') {
    styles = 'bg-[#ff6b00] text-white border-transparent';
  } else if (variant === 'orange') {
    styles = 'bg-[#ff6b00]/15 text-[#ff6b00] border-[#ff6b00]/30';
  } else if (variant === 'amber') {
    styles = 'bg-amber-500/15 text-amber-400 border-amber-500/30';
  }

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 text-xs font-sans font-medium border rounded-none ${styles}`}>
      {label}
    </span>
  );
};
