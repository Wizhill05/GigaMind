import React from 'react';

interface AgentBadgeProps {
  agent: string;
}

export const AgentBadge: React.FC<AgentBadgeProps> = ({ agent }) => {
  const normalized = (agent || 'user').toLowerCase();

  let bg = 'bg-[#1e2029] text-[#c1c5d0] border-[#262936]';
  let label = agent;

  if (normalized.includes('claude')) {
    bg = 'bg-[#f59e0b]/10 text-[#f59e0b] border-[#f59e0b]/30';
    label = 'Claude';
  } else if (normalized.includes('gpt') || normalized.includes('openai')) {
    bg = 'bg-[#10b981]/10 text-[#10b981] border-[#10b981]/30';
    label = 'GPT';
  } else if (normalized.includes('gemini')) {
    bg = 'bg-[#06b6d4]/10 text-[#06b6d4] border-[#06b6d4]/30';
    label = 'Gemini';
  } else if (normalized.includes('user')) {
    bg = 'bg-[#a855f7]/10 text-[#a855f7] border-[#a855f7]/30';
    label = 'User';
  } else if (normalized.includes('system') || normalized.includes('mcp')) {
    bg = 'bg-[#00f2fe]/10 text-[#00f2fe] border-[#00f2fe]/30';
    label = 'System';
  }

  return (
    <span className={`inline-flex items-center px-2 py-0.5 text-xs font-sans font-medium border rounded-md ${bg}`}>
      {label}
    </span>
  );
};

export const CategoryBadge: React.FC<{ category: string }> = ({ category }) => {
  return (
    <span className="inline-flex items-center px-2 py-0.5 text-xs font-sans text-[#8a8f9e] bg-[#101216] border border-[#1e2029] rounded-md">
      {category || 'general'}
    </span>
  );
};

export const RenderPill: React.FC<{ label: string; variant?: 'purple' | 'purpleFilled' | 'emerald' | 'gray' }> = ({
  label,
  variant = 'gray',
}) => {
  let styles = 'bg-[#1e2029] text-[#c1c5d0] border-[#262936]';

  if (variant === 'purpleFilled') {
    styles = 'bg-[#5b0e89] text-white border-transparent';
  } else if (variant === 'purple') {
    styles = 'bg-[#5b0e89]/20 text-[#a855f7] border-[#5b0e89]/40';
  } else if (variant === 'emerald') {
    styles = 'bg-[#10b981]/15 text-emerald-400 border-emerald-500/30';
  }

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 text-xs font-sans font-medium border rounded-md ${styles}`}>
      {label}
    </span>
  );
};
