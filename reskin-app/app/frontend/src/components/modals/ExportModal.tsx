import { useState } from 'react';
import { api, type GodotExportResponse } from '../../api/client';
import { useStore } from '../../state/store';

export function ExportModal({ onClose }: { onClose: () => void }) {
  const project = useStore((s) => s.project);
  const [target, setTarget] = useState<'godot' | 'spine'>('godot');
  const [skin, setSkin] = useState(useStore.getState().activeSkin);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<GodotExportResponse | null>(null);
  const [spineResult, setSpineResult] = useState('');
  const [copied, setCopied] = useState(false);
  if (!project) return null;

  const runExport = async () => {
    setBusy(true); setError(''); setResult(null); setSpineResult(''); setCopied(false);
    try {
      const state = useStore.getState();
      // Edits in this version of the editor are scoped to the displayed look.
      const edits = skin === state.activeSkin ? state.edits : {};
      if (target === 'godot') {
        setResult(await api.exportGodot(skin, edits, [...state.hidden]));
      } else {
        const exported = await api.exportSkin(skin, edits);
        setSpineResult([exported.spine_json, exported.atlas_image, exported.atlas_meta].join('\n'));
      }
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };

  return <div className="modal-backdrop" onClick={() => { if (!busy) onClose(); }}>
    <div className="modal" onClick={(e) => e.stopPropagation()}>
      <header><h2>Export character</h2><button disabled={busy} onClick={onClose}>×</button></header>
      <div className="modal-body">
        <label className="field"><span>Format</span>
          <select disabled={busy} value={target} onChange={(e) => { setTarget(e.target.value as 'godot' | 'spine'); setResult(null); setSpineResult(''); setError(''); }}>
            <option value="godot">Godot 4 · native cutout</option>
            <option value="spine">Spine · existing export</option>
          </select>
        </label>
        <label className="field"><span>Look</span>
          <select disabled={busy} value={skin} onChange={(e) => { setSkin(e.target.value); setResult(null); setSpineResult(''); }}>
            {Array.from(new Set(['default', ...project.skins])).map((name) => <option key={name}>{name}</option>)}
          </select>
        </label>
        <p className="muted">{target === 'godot'
          ? 'Creates an editable skeleton, animation library and textures in a new folder. Includes the original look, the selected look, part visibility and saved transforms. Meshes and constraints require additional support.'
          : 'Exports the generated look using the existing Spine atlas pipeline.'}</p>
        {error && <div className="report" role="alert" style={{ whiteSpace: 'pre-wrap' }}>{error}</div>}
        {result && <>
          <div className="report">Exported {result.bones} bones, {result.parts} parts and {result.animations.length} animation{result.animations.length === 1 ? '' : 's'}.</div>
          <label className="field"><span>Open this project in Godot</span><input type="text" readOnly value={result.project} /></label>
          <p className="muted">Run the preview to switch animations and looks. To use it in your game, copy character.tscn, character.gd, animations.tres and textures together into one folder.</p>
          <button onClick={async () => {
            try { await navigator.clipboard.writeText(result.project); setCopied(true); }
            catch { setError('Select and copy the project path above.'); }
          }}>{copied ? 'Copied' : 'Copy project path'}</button>
        </>}
        {spineResult && <div className="report" style={{ whiteSpace: 'pre-wrap' }}>{spineResult}</div>}
        <div className="actions"><button disabled={busy} onClick={onClose}>Close</button>
          <button className="primary" disabled={busy} onClick={runExport}>{busy ? 'Exporting…' : 'Export'}</button>
        </div>
      </div>
    </div>
  </div>;
}
