import React, { useEffect, useMemo, useState } from 'react';
import DOMPurify from 'dompurify';
import {
  AlertCircle,
  ListTodo,
  FileDown,
  CheckCircle2,
  Code2,
  Download,
  ExternalLink,
  File,
  FileSpreadsheet,
  Image as ImageIcon,
  Loader2,
  Maximize2,
  RotateCcw,
  X,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import { ArtifactValidation, AttachmentPayload } from '../../contracts/domain/session';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';
import { renderMarkdown } from '../../domain/markdown';
import { abrirEmJanela, abrirUrlEmJanela } from '../../runtime/window-open';
import { useWorkbenchStore } from '../../stores/workbench-store';

interface AttachmentRendererProps {
  sessionId: string;
  rawAttachment: unknown;
  validation?: ArtifactValidation;
}

type RawRecord = Record<string, unknown>;

const LABELS: Record<string, { badge: string; subtitle: string }> = {
  xlsx: { badge: 'XLSX', subtitle: 'Planilha operacional pronta para baixar' },
  csv: { badge: 'CSV', subtitle: 'Preview dos dados e arquivo para download' },
  pdf: { badge: 'PDF', subtitle: 'Relatório com preview e download' },
  pptx: { badge: 'PPTX', subtitle: 'Apresentação pronta para baixar' },
  docx: { badge: 'DOCX', subtitle: 'Documento pronto para baixar' },
  png: { badge: 'PNG', subtitle: 'Imagem gerada' },
  jpg: { badge: 'JPG', subtitle: 'Imagem gerada' },
  jpeg: { badge: 'JPEG', subtitle: 'Imagem gerada' },
  webp: { badge: 'WEBP', subtitle: 'Imagem gerada' },
  svg: { badge: 'SVG', subtitle: 'Diagrama com preview e fonte' },
  html: { badge: 'HTML', subtitle: 'Dashboard com preview seguro e fonte' },
  markdown: { badge: 'MD', subtitle: 'Documento Markdown' },
  ascii: { badge: 'TXT', subtitle: 'Visualização em texto' },
  chart_json: { badge: 'CHART', subtitle: 'Visualização baseada nos dados retornados' },
};

function stringValue(record: RawRecord, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.length > 0) return value;
  }
  return undefined;
}

function normalizeAttachment(raw: unknown): AttachmentPayload | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const record = raw as RawRecord;
  const chartData = record.chart_data ?? record.chartData;
  return {
    artifactId: stringValue(record, 'artifact_id', 'artifactId'),
    caminho: stringValue(record, 'caminho'),
    ausente: record.ausente === true,
    type: stringValue(record, 'type')?.toLowerCase(),
    filename: stringValue(record, 'filename'),
    title: stringValue(record, 'title'),
    mimeType: stringValue(record, 'mime_type', 'mimeType'),
    contentBase64: stringValue(record, 'content_base64', 'contentBase64'),
    content: stringValue(record, 'content'),
    chartData: chartData && typeof chartData === 'object' && !Array.isArray(chartData)
      ? chartData as Record<string, unknown>
      : undefined,
    verifiedPreviewBase64: stringValue(record, 'verified_preview_base64', 'verifiedPreviewBase64'),
    verifiedPreviewMimeType: stringValue(record, 'verified_preview_mime_type', 'verifiedPreviewMimeType'),
    verifiedPreviewFilename: stringValue(record, 'verified_preview_filename', 'verifiedPreviewFilename'),
  };
}

function inferType(attachment: AttachmentPayload): string {
  if (attachment.type) return attachment.type;
  const filename = attachment.filename?.toLowerCase() || '';
  const extension = filename.includes('.') ? filename.split('.').at(-1) : undefined;
  if (extension) return extension;
  const mime = attachment.mimeType || '';
  if (mime.includes('html')) return 'html';
  if (mime.includes('svg')) return 'svg';
  if (mime.includes('pdf')) return 'pdf';
  if (mime.includes('csv')) return 'csv';
  if (mime.startsWith('image/')) return mime.split('/')[1];
  return 'file';
}

function inferMime(type: string, explicit?: string): string {
  if (explicit) return explicit;
  return ({
    html: 'text/html', svg: 'image/svg+xml', pdf: 'application/pdf', csv: 'text/csv',
    png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp',
    markdown: 'text/markdown', ascii: 'text/plain', chart_json: 'application/json',
  } as Record<string, string>)[type] || 'application/octet-stream';
}

function decodeBase64(value?: string): string {
  if (!value) return '';
  try {
    const bytes = Uint8Array.from(atob(value), character => character.charCodeAt(0));
    return new TextDecoder('utf-8').decode(bytes);
  } catch {
    return '';
  }
}

function parseCsv(text: string, maximumRows = 9): string[][] {
  const rows: string[][] = [];
  for (const line of text.replace(/\r\n/g, '\n').split('\n')) {
    if (!line.trim() || rows.length >= maximumRows) continue;
    const cells: string[] = [];
    let current = '';
    let quoted = false;
    for (let index = 0; index < line.length; index += 1) {
      const character = line[index];
      if (quoted && character === '"' && line[index + 1] === '"') {
        current += '"';
        index += 1;
      } else if (character === '"') quoted = !quoted;
      else if (character === ',' && !quoted) {
        cells.push(current);
        current = '';
      } else current += character;
    }
    cells.push(current);
    rows.push(cells);
  }
  return rows;
}

function ChartPreview({ chartData }: { chartData: Record<string, unknown> }) {
  const data = chartData.data && typeof chartData.data === 'object' ? chartData.data as RawRecord : chartData;
  const labels = Array.isArray(data.labels) ? data.labels.map(String) : [];
  const datasets = Array.isArray(data.datasets) ? data.datasets : [];
  const firstDataset = datasets[0] && typeof datasets[0] === 'object' ? datasets[0] as RawRecord : null;
  const values = firstDataset && Array.isArray(firstDataset.data)
    ? firstDataset.data.map(value => Number(value)).filter(Number.isFinite)
    : [];
  const magnitude = Math.max(...values.map(value => Math.abs(value)), 1);

  if (!values.length) return <pre className="overflow-auto p-4 text-xs">{JSON.stringify(chartData, null, 2)}</pre>;
  return (
    <div className="flex h-52 items-end gap-2 p-4" role="img" aria-label="Visualização dos dados do gráfico">
      {values.map((value, index) => (
        <div key={`${labels[index] || index}-${index}`} className="flex min-w-0 flex-1 flex-col items-center justify-end gap-1">
          <span className="text-[10px] font-semibold text-zinc-700">{value}</span>
          <div
            className={value < 0 ? 'w-full rounded-t bg-red-400' : 'w-full rounded-t bg-gold'}
            style={{ height: `${Math.max(8, (Math.abs(value) / magnitude) * 130)}px` }}
          />
          <span className="max-w-full truncate text-[10px] text-zinc-500">{labels[index] || index + 1}</span>
        </div>
      ))}
    </div>
  );
}

export const AttachmentRenderer: React.FC<AttachmentRendererProps> = ({ sessionId, rawAttachment, validation }) => {
  const [resolvedRaw, setResolvedRaw] = useState(rawAttachment);
  const [isHydrating, setIsHydrating] = useState(false);
  const [hydrateError, setHydrateError] = useState('');
  const [isExpanded, setIsExpanded] = useState(false);
  const [showSource, setShowSource] = useState(false);
  const [tarefa, setTarefa] = useState<'idle' | 'enviando' | 'ok' | 'erro'>('idle');
  const [pdf, setPdf] = useState<'idle' | 'gerando' | 'erro'>('idle');
  const [zoom, setZoom] = useState(1);
  const attachment = useMemo(() => normalizeAttachment(resolvedRaw), [resolvedRaw]);
  const type = attachment ? inferType(attachment) : 'file';
  const mime = attachment ? inferMime(type, attachment.mimeType) : 'application/octet-stream';
  const sourceText = attachment?.content ?? (
    ['html', 'svg', 'csv', 'markdown', 'ascii'].includes(type) ? decodeBase64(attachment?.contentBase64) : ''
  );
  const safeHtml = useMemo(() => DOMPurify.sanitize(sourceText, {
    WHOLE_DOCUMENT: true,
    FORBID_TAGS: ['script'],
  }), [sourceText]);
  const fileUrl = attachment?.contentBase64
    ? `data:${mime};base64,${attachment.contentBase64}`
    : attachment?.content
      ? `data:${mime};charset=utf-8,${encodeURIComponent(attachment.content)}`
      : attachment?.chartData
        ? `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(attachment.chartData, null, 2))}`
        : '';
  const verifiedPreviewUrl = attachment?.verifiedPreviewBase64
    ? `data:${attachment.verifiedPreviewMimeType || 'image/png'};base64,${attachment.verifiedPreviewBase64}`
    : '';

  useEffect(() => {
    const normalized = normalizeAttachment(rawAttachment);
    if (!normalized?.artifactId || normalized.contentBase64 || normalized.content || normalized.chartData) return;
    let cancelled = false;
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    setIsHydrating(true);
    setHydrateError('');
    void apiClient.get<{ attachment?: unknown }>(
      `/sentury/sessions/${encodeURIComponent(sessionId)}/artifacts/${encodeURIComponent(normalized.artifactId)}?user_id=${encodeURIComponent(config.userId)}`,
      { headers: authHeaders() },
    ).then(result => {
      if (!cancelled && result.attachment) setResolvedRaw(result.attachment);
    }).catch(() => {
      if (!cancelled) setHydrateError('O artefato está referenciado, mas o conteúdo não pôde ser recuperado agora.');
    }).finally(() => {
      if (!cancelled) setIsHydrating(false);
    });
    return () => { cancelled = true; };
  }, [rawAttachment, sessionId]);

  useEffect(() => {
    if (!isExpanded) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsExpanded(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isExpanded]);

  if (!attachment) return null;

  const filename = attachment.filename || attachment.title || `resultado.${type === 'file' ? 'bin' : type}`;
  const labels = LABELS[type] || { badge: type.toUpperCase(), subtitle: 'Arquivo pronto para baixar' };
  const isImage = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'].includes(type);
  const canPreview = isImage || ['html', 'pdf', 'csv', 'markdown', 'ascii', 'chart_json'].includes(type);
  const addArtifact = useWorkbenchStore(state => state.addArtifact);
  const setActiveArtifact = useWorkbenchStore(state => state.setActiveArtifact);
  const canShowSource = ['html', 'svg', 'markdown', 'ascii'].includes(type) && Boolean(sourceText);

  const download = () => {
    if (!fileUrl) return;
    const anchor = document.createElement('a');
    anchor.href = fileUrl;
    anchor.download = filename;
    anchor.click();
  };

  const openExternal = () => {
    if (fileUrl) { abrirUrlEmJanela(fileUrl); return; }
    if (type === 'markdown') { abrirEmJanela(filename, renderMarkdown(sourceText)); return; }
    if (sourceText) abrirEmJanela(filename, type === 'html' ? safeHtml : `<pre>${sourceText.replace(/[<&]/g, c => (c === '<' ? '&lt;' : '&amp;'))}</pre>`);
  };

  // Expandir abre AO LADO; a tela cheia continua no botao de janela.
  const expandirAoLado = () => {
    if (type === 'markdown' && sourceText) {
      const id = `att-${sessionId}-${filename}`;
      addArtifact({ id, type: 'markdown', title: filename, sessionId, createdAt: new Date().toISOString(), content: sourceText });
      setActiveArtifact(id);
      return;
    }
    setIsExpanded(true);
  };

  const enviarProTasks = async () => {
    setTarefa('enviando');
    try {
      await apiClient.post('/sentury/acoes/from-plan', { markdown: sourceText, title: filename.replace(/\.md$/i, '') }, { headers: authHeaders() });
      setTarefa('ok');
    } catch {
      setTarefa('erro');
    } finally {
      window.setTimeout(() => setTarefa('idle'), 2400);
    }
  };

  // O plano ja esta pronto: converter no backend nao gasta token.
  const exportarPdf = async () => {
    const nome = filename.replace(/\.md$/i, '') + '.pdf';
    setPdf('gerando');
    try {
      const config = getRuntimeConfig();
      const resposta = await fetch(`${config.apiUrl}/sentury/render/pdf`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ markdown: sourceText, title: filename, filename: nome }),
      });
      if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
      const url = URL.createObjectURL(await resposta.blob());
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = nome;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 4000);
      setPdf('idle');
    } catch {
      setPdf('erro');
      window.setTimeout(() => setPdf('idle'), 2400);
    }
  };

  const preview = (expanded = false) => {
    if (showSource && expanded) {
      return <pre className="h-full overflow-auto whitespace-pre-wrap bg-[#181714] p-5 font-mono text-xs leading-5 text-stone-100">{sourceText}</pre>;
    }
    if (type === 'html') return <iframe title={`Preview de ${filename}`} sandbox="" srcDoc={safeHtml} className="h-full min-h-64 w-full bg-white" />;
    if (type === 'pdf') return <iframe title={`Preview de ${filename}`} src={fileUrl} className="h-full min-h-64 w-full bg-white" />;
    if (isImage) return (
      <div className="flex h-full min-h-48 items-center justify-center overflow-auto bg-[radial-gradient(circle_at_center,#fff_0,#f3f1ea_100%)] p-4">
        <img
          src={verifiedPreviewUrl || fileUrl}
          alt={filename}
          className="max-h-full max-w-full origin-center object-contain transition-transform duration-150"
          style={{ transform: `scale(${expanded ? zoom : 1})` }}
        />
      </div>
    );
    if (type === 'csv') {
      const rows = parseCsv(sourceText);
      return (
        <div className="overflow-auto">
          <table className="w-full border-collapse text-left text-xs">
            <tbody>{rows.map((cells, rowIndex) => (
              <tr key={rowIndex} className="border-b border-stone-200">
                {cells.map((cell, cellIndex) => rowIndex === 0
                  ? <th key={cellIndex} className="bg-stone-100 px-3 py-2 font-semibold">{cell}</th>
                  : <td key={cellIndex} className="px-3 py-2 text-zinc-700">{cell}</td>)}
              </tr>
            ))}</tbody>
          </table>
        </div>
      );
    }
    if (type === 'markdown') {
      return <div className="bubble__md prose prose-sm max-w-none p-4" dangerouslySetInnerHTML={{ __html: renderMarkdown(sourceText) }} />;
    }
    if (type === 'ascii') return <pre className="overflow-auto whitespace-pre p-4 font-mono text-xs leading-5">{sourceText}</pre>;
    if (type === 'chart_json' && attachment.chartData) return <ChartPreview chartData={attachment.chartData} />;
    return null;
  };

  return (
    <>
      <section className="mt-4 max-w-2xl overflow-hidden rounded-xl border border-stone-300 bg-[#fffdf8] shadow-[0_10px_28px_rgba(45,39,28,0.08)]">
        <div className="flex items-center gap-3 px-3.5 py-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gold-soft text-gold-ink">
            {isImage ? <ImageIcon className="h-4 w-4" /> : type === 'csv' || type === 'xlsx' ? <FileSpreadsheet className="h-4 w-4" /> : <File className="h-4 w-4" />}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-zinc-900">{filename}</p>
            <p className="truncate text-[11px] text-zinc-500" title={attachment.caminho}>
              {attachment.ausente ? `Saiu de ${attachment.caminho}` : attachment.caminho ? `Salvo em ${attachment.caminho}` : labels.subtitle}
            </p>
          </div>
          <span className="rounded-md border border-stone-300 px-1.5 py-0.5 text-[10px] font-bold text-zinc-600">{labels.badge}</span>
          {validation?.status === 'ok' && <span title="Artefato validado"><CheckCircle2 className="h-4 w-4 text-emerald-600" /></span>}
          {validation?.status === 'warning' && <span title="Artefato com alertas"><AlertCircle className="h-4 w-4 text-gold-hover" /></span>}
          {type === 'markdown' && sourceText ? (
            <>
              <button type="button" onClick={() => void enviarProTasks()} className="rounded-md p-1.5 text-zinc-500 hover:bg-stone-100 hover:text-zinc-900" title={tarefa === 'ok' ? 'Salvo em Tarefas' : tarefa === 'erro' ? 'Não consegui salvar' : 'Salvar em Tarefas'}>
                <ListTodo className={`h-4 w-4 ${tarefa === 'ok' ? 'text-emerald-600' : tarefa === 'erro' ? 'text-red-600' : ''}`} />
              </button>
              <button type="button" onClick={() => void exportarPdf()} className="rounded-md p-1.5 text-zinc-500 hover:bg-stone-100 hover:text-zinc-900" title={pdf === 'gerando' ? 'Gerando PDF…' : 'Exportar PDF'}>
                <FileDown className={`h-4 w-4 ${pdf === 'erro' ? 'text-red-600' : ''}`} />
              </button>
            </>
          ) : null}
          {canPreview && <button type="button" onClick={expandirAoLado} className="rounded-md p-1.5 text-zinc-500 hover:bg-stone-100 hover:text-zinc-900" title="Expandir ao lado"><Maximize2 className="h-4 w-4" /></button>}
          <button type="button" onClick={openExternal} className="rounded-md p-1.5 text-zinc-500 hover:bg-stone-100 hover:text-zinc-900" title="Abrir em outra janela"><ExternalLink className="h-4 w-4" /></button>
          {canShowSource && <button type="button" onClick={() => { setShowSource(true); setIsExpanded(true); }} className="rounded-md p-1.5 text-zinc-500 hover:bg-stone-100 hover:text-zinc-900" title="Ver código-fonte"><Code2 className="h-4 w-4" /></button>}
          {fileUrl && <button type="button" onClick={download} className="rounded-md p-1.5 text-zinc-500 hover:bg-stone-100 hover:text-zinc-900" title="Baixar"><Download className="h-4 w-4" /></button>}
        </div>
        {isHydrating && <div className="flex items-center gap-2 border-t border-stone-200 px-4 py-3 text-xs text-zinc-500"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Recuperando artefato persistido…</div>}
        {hydrateError && <p className="border-t border-red-200 bg-red-50 px-4 py-3 text-xs text-red-700">{hydrateError}</p>}
        {canPreview && !isHydrating && !hydrateError && (
          <button type="button" onClick={expandirAoLado} className="block max-h-72 w-full overflow-hidden border-t border-stone-200 text-left" aria-label={`Abrir preview de ${filename}`}>
            {preview()}
          </button>
        )}
      </section>

      {isExpanded && (
        <div className="fixed inset-0 z-[80] flex animate-[sentury-modal-in_180ms_ease-out] flex-col bg-zinc-950/82 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label={`Preview de ${filename}`}>
          <div className="mx-auto flex w-full max-w-7xl items-center gap-2 rounded-t-xl border border-zinc-700 bg-[#201f1c] px-3 py-2 text-stone-100">
            <strong className="min-w-0 flex-1 truncate text-sm">{filename}</strong>
            {canShowSource && <button type="button" onClick={() => setShowSource(value => !value)} className={`rounded-md px-2.5 py-1.5 text-xs ${showSource ? 'bg-gold text-zinc-950' : 'hover:bg-zinc-800'}`}><Code2 className="mr-1 inline h-3.5 w-3.5" />{showSource ? 'Preview' : 'Fonte'}</button>}
            {isImage && !showSource && <>
              <button type="button" onClick={() => setZoom(value => Math.max(.4, value - .2))} className="rounded-md p-1.5 hover:bg-zinc-800" title="Reduzir zoom"><ZoomOut className="h-4 w-4" /></button>
              <button type="button" onClick={() => setZoom(1)} className="rounded-md p-1.5 hover:bg-zinc-800" title="Restaurar zoom"><RotateCcw className="h-4 w-4" /></button>
              <button type="button" onClick={() => setZoom(value => Math.min(3, value + .2))} className="rounded-md p-1.5 hover:bg-zinc-800" title="Aumentar zoom"><ZoomIn className="h-4 w-4" /></button>
            </>}
            <button type="button" onClick={openExternal} className="rounded-md p-1.5 hover:bg-zinc-800" title="Abrir em outra janela"><ExternalLink className="h-4 w-4" /></button>
            {fileUrl && <button type="button" onClick={download} className="rounded-md p-1.5 hover:bg-zinc-800" title="Baixar"><Download className="h-4 w-4" /></button>}
            <button type="button" onClick={() => setIsExpanded(false)} className="rounded-md p-1.5 hover:bg-zinc-800" title="Fechar"><X className="h-4 w-4" /></button>
          </div>
          <div className="mx-auto min-h-0 w-full max-w-7xl flex-1 overflow-auto rounded-b-xl border-x border-b border-zinc-700 bg-[#f6f5f0]">
            {preview(true)}
          </div>
        </div>
      )}
    </>
  );
};
