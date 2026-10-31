import React, { useEffect, useState } from 'react';
import { apiClient } from '../../transport/http-client';
import { authHeaders } from '../../runtime/config';
import { funcaoPorId } from '../../runtime/funcoes-nativas';
import { IconeDaFuncao } from './IconeDaFuncao';
import { PilulaDoResidente } from '../residentes/NaConversa';
import { useHQ } from '../residentes/useEsperando';

/** Os mesmos tokens que o campo de texto desenha: `@nome`, `/nome` e `[nome]`. */
const TOKEN = /((?:^|(?<=\s))(?:[@/][a-z0-9][a-z0-9-]*|\[[a-z0-9][a-z0-9-]*\]))/gi;

// Uma busca para todas as mensagens: sem a lista, `/tmp` no meio da frase viraria skill.
let skillsConhecidas: Promise<Set<string>> | null = null;
function nomesDeSkills(): Promise<Set<string>> {
  skillsConhecidas ??= apiClient.get<{ skills?: Array<{ name?: unknown }> }>('/sentury/skills', { headers: authHeaders() })
    .then(r => new Set((r.skills || []).flatMap(s => (typeof s?.name === 'string' ? [s.name.toLowerCase()] : []))))
    .catch(() => { skillsConhecidas = null; return new Set<string>(); });
  return skillsConhecidas;
}

/** A mensagem da pessoa como ela a escreveu no campo, com os badges no lugar. */
export const TextoComTokens: React.FC<{ texto: string }> = ({ texto }) => {
  const residentes = useHQ().agentes;
  const [skills, setSkills] = useState<Set<string>>(new Set());
  const temSkill = /(?:^|\s)(?:\/|\[)[a-z0-9]/i.test(texto);
  useEffect(() => {
    if (!temSkill) return;
    let vivo = true;
    void nomesDeSkills().then(nomes => { if (vivo) setSkills(nomes); });
    return () => { vivo = false; };
  }, [temSkill]);

  return (
    <>
      {texto.split(TOKEN).map((parte, i) => {
        if (!parte) return null;
        const nome = parte.replace(/^[@/[]|\]$/g, '').toLowerCase();
        if (parte.startsWith('@')) {
          if (residentes.some(a => a.nome === nome)) return <PilulaDoResidente key={i} nome={nome} escura />;
          const funcao = funcaoPorId(nome);
          if (funcao) {
            // No balão escuro: intenção em dourado claro, acesso em selo translúcido.
            const estilo = funcao.tipo === 'acesso'
              ? 'border border-white/25 bg-white/10 text-white'
              : 'border border-[#ecd98a] bg-[#fbf3d0] text-[#4d4000]';
            return (
              <span key={i} title={funcao.descricao} className={`mx-0.5 inline-flex items-center gap-1 rounded-md px-1.5 align-middle text-xs font-semibold leading-5 ${estilo}`}>
                <IconeDaFuncao id={funcao.id} className={`h-3 w-3 ${funcao.tipo === 'acesso' ? 'text-gold' : ''}`} />@{funcao.rotulo}
              </span>
            );
          }
        } else if (skills.has(nome) || (parte.startsWith('[') && i === 1)) {
          return <span key={i} title={parte} className="mx-0.5 inline-flex rounded-md border border-gold/35 bg-gold/15 px-1.5 py-px align-middle text-xs font-bold leading-5 text-gold">{nome}</span>;
        }
        return <React.Fragment key={i}>{parte}</React.Fragment>;
      })}
    </>
  );
};
