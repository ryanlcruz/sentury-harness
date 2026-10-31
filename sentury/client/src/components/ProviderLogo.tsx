import React, { useState } from 'react';

// Logos servidas dos assets empacotados do RobinBandit, sem CDN nem lista
// parcial mantida pelo client. Se um provedor novo não tiver SVG, monograma.
const ALIASES: Record<string, string> = {
  openai_compat: 'openai',
  anthropic: 'claude',
  google: 'gemini',
  github_models: 'github',
  workers_ai: 'workersai',
  ultra: 'openrouter',
  ultra_max: 'openrouter',
};

const CORES: Record<string, string> = {
  cerebras: '#f15a24',
  claude: '#d97757',
  claude_code: '#d97757',
  cohere: '#39594d',
  deepinfra: '#6558f5',
  fireworks: '#6f46ff',
  gemini: '#4285f4',
  github: '#181717',
  groq: '#f55036',
  huggingface: '#ffcc4d',
  mistral: '#f7a900',
  nvidia: '#76b900',
  ollama: '#111111',
  openai: '#111111',
  openrouter: '#5b5bf7',
  sambanova: '#ff5a36',
  together: '#0f6fff',
  workersai: '#f38020',
  fallback: '#8a8172',
};

interface ProviderLogoProps {
  providerKey: string;
  label: string;
  className?: string;
}

export const ProviderLogo: React.FC<ProviderLogoProps> = ({ providerKey, label, className = 'h-7 w-7' }) => {
  const [fonteQueFalhou, setFonteQueFalhou] = useState<string | null>(null);
  const bruto = (providerKey || '').toLowerCase();
  const nome = ALIASES[bruto] || bruto.replace(/[^a-z0-9_]/g, '');
  const cor = CORES[nome] || '#71717a';
  const fonte = `/provider-logos/${nome}.svg`;

  if (fonteQueFalhou === fonte || !nome) {
    return (
      <span
        aria-label={`Logo ${label}`}
        className={`flex shrink-0 items-center justify-center rounded-lg text-[10px] font-black tracking-tight text-white shadow-sm ${className}`}
        style={{ backgroundColor: cor }}
      >
        {(label || nome).slice(0, 2).toUpperCase()}
      </span>
    );
  }

  return (
    <span className={`flex shrink-0 items-center justify-center rounded-lg border border-stone-200 bg-white shadow-sm ${className}`}>
      <img
        src={fonte}
        alt={`Logo ${label}`}
        className="h-[64%] w-[64%] object-contain"
        loading="lazy"
        onError={() => setFonteQueFalhou(fonte)}
      />
    </span>
  );
};
