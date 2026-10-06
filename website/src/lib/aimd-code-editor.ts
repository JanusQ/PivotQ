import * as monaco from 'monaco-editor/editor/editor.api.js';
import 'monaco-editor/languages/definitions/python/register.js';
import EditorWorker from 'monaco-editor/editor/editor.worker.js?worker';

export function mountCodeEditor(source: HTMLElement) {
  const host = source.querySelector<HTMLElement>('[data-code-editor]')!;
  const fallback = source.querySelector<HTMLElement>('[data-code-fallback]')!;
  const environment = globalThis as typeof globalThis & { MonacoEnvironment?: { getWorker: () => Worker } };
  environment.MonacoEnvironment = { getWorker: () => new EditorWorker() };
  monaco.editor.defineTheme('aimd-light', {
    base: 'vs', inherit: true,
    rules: [
      { token: '', foreground: '000000' },
      { token: 'comment', foreground: '008000' },
      { token: 'string', foreground: 'A31515' },
      { token: 'keyword', foreground: '0000FF' },
      { token: 'number', foreground: '098658' },
      { token: 'delimiter', foreground: '0000FF' },
      { token: 'identifier', foreground: '000000' },
    ],
    colors: {
      'editor.background': '#FFFFFF', 'editor.foreground': '#000000',
      'editorLineNumber.foreground': '#1686A4', 'editorLineNumber.activeForeground': '#005A99',
      'editor.lineHighlightBackground': '#FAFAFA', 'editor.lineHighlightBorder': '#EEEEEE',
      'editor.selectionBackground': '#D8E9FA', 'editor.inactiveSelectionBackground': '#E8F0F8',
      'editorCursor.foreground': '#003F88', 'editorGutter.background': '#FFFFFF',
      'editorOverviewRuler.border': '#FFFFFF', 'minimap.background': '#FFFFFF',
      'minimapSlider.background': '#426E9220', 'minimapSlider.hoverBackground': '#426E9240',
      'scrollbarSlider.background': '#91A4B840', 'scrollbarSlider.hoverBackground': '#91A4B870',
    },
  });
  host.hidden = false;
  let compact = host.clientWidth < 440;
  let editor: monaco.editor.IStandaloneCodeEditor;
  try {
    editor = monaco.editor.create(host, {
      value: source.dataset.modelSource || '', language: 'python', theme: 'aimd-light',
      readOnly: true, domReadOnly: true, ariaLabel: '水分子模型代码',
      fontFamily: 'Consolas, "SFMono-Regular", "Liberation Mono", monospace',
      fontSize: 14, lineHeight: 25, fontWeight: '400', fontLigatures: false,
      lineNumbers: 'on', lineNumbersMinChars: 3, lineDecorationsWidth: 12,
      glyphMargin: false, folding: false, renderLineHighlight: 'line',
      minimap: { enabled: !compact, renderCharacters: true, maxColumn: 90, size: 'fit', showSlider: 'always' },
      padding: { top: 16, bottom: 16 }, automaticLayout: true,
      scrollBeyondLastLine: false, wordWrap: compact ? 'on' : 'off', contextmenu: false,
      bracketPairColorization: { enabled: true }, renderWhitespace: 'none',
      overviewRulerLanes: 0, hideCursorInOverviewRuler: true,
      scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10, useShadows: true },
    });
  } catch (error) { host.hidden = true; throw error; }
  fallback.hidden = true; source.dataset.editorReady = 'true';
  const resizeObserver = new ResizeObserver(() => {
    const nextCompact = host.clientWidth < 440;
    if (nextCompact === compact) return;
    compact = nextCompact;
    editor.updateOptions({
      minimap: { enabled: !compact }, wordWrap: compact ? 'on' : 'off',
      fontSize: 14, lineHeight: 25,
    });
  });
  resizeObserver.observe(host);
  const decorations = editor.createDecorationsCollection();
  function highlight(line: number) {
    if (line < 0 || line >= editor.getModel()!.getLineCount()) return;
    const number = line + 1;
    decorations.set([{ range: new monaco.Range(number, 1, number, 1), options: { isWholeLine: true, className: 'analysis-editor-linked-line', minimap: { color: '#ABD0F4', position: monaco.editor.MinimapPosition.Inline } } }]);
    editor.setPosition({ lineNumber: number, column: 1 });
    editor.revealLineInCenterIfOutsideViewport(number);
    source.dataset.selectedLine = String(number);
  }
  window.addEventListener('pagehide', event => {
    if (event.persisted) return;
    resizeObserver.disconnect();
    const model = editor.getModel(); editor.dispose(); model?.dispose();
  }, { once: true });
  return { highlight };
}
