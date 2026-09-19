import { useEffect, useState } from 'react';
import { api, type HandoffJob } from '../../api/client';
import { snapshotCanvas } from '../../canvasSnapshot';
import { useStore } from '../../state/store';

export function CodexHandoffPanel({ onImported }: { onImported: (job: HandoffJob) => void }) {
  const method = useStore((s) => s.reskinMethod);
  const [prompt, setPrompt] = useState('');
  const [name, setName] = useState('');
  const [jobs, setJobs] = useState<HandoffJob[]>([]);
  const [job, setJob] = useState<HandoffJob | null>(null);
  const [image, setImage] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let active = true;
    api.listHandoffs().then((items) => { if (active) setJobs(items); })
      .catch((e) => { if (active) setError(String(e.message)); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!job || job.status !== 'prepared') return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const updated = await api.getHandoff(job.id);
        if (!active) return;
        if (updated.status === 'imported') {
          onImported(updated);
          return;
        }
      } catch (e) {
        if (active) setError(`Could not check task: ${(e as Error).message}`);
      }
      if (active) timer = setTimeout(poll, 2500);
    };
    timer = setTimeout(poll, 2500);
    return () => { active = false; clearTimeout(timer); };
  }, [job, onImported]);

  const prepare = async () => {
    setBusy(true); setError('');
    try {
      const skinName = name.trim();
      if (!/^[a-z0-9][a-z0-9_-]{0,47}$/.test(skinName)) {
        throw new Error('Use 1–48 lowercase letters, digits, hyphens or underscores for the look name.');
      }
      if (method === 'atlas') {
        const snapshot = await snapshotCanvas();
        if (!snapshot) throw new Error('Wait for the character to load before preparing a task.');
        await api.uploadSnapshot(snapshot, skinName);
      }
      const prepared = await api.prepareHandoff(skinName, prompt, method);
      setJob(prepared);
      setJobs((items) => [prepared, ...items]);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };

  const request = job ? `Use $reskin-in-codex to complete the prepared Reskin Studio task.\nRead the task manifest at:\n${job.manifest_path}\nInspect its input images, use Codex's built-in image generation tool to make the requested edit, then import the saved result into this task. Use the complete canvas including padding. No paid API fallback.` : '';

  return (
    <div className="handoff-panel">
      <p className="muted">Generate in Codex, then import the image here. Original part outlines are preserved locally. No image API key is needed in this app.</p>
      {error && <div role="alert" className="report">{error}</div>}
      {!job ? <>
        {jobs.length > 0 && <label className="field">
          <span>Resume a task</span>
          <select value="" onChange={(e) => {
            const selected = jobs.find((item) => item.id === e.target.value);
            if (!selected) return;
            setError('');
            if (selected.status === 'imported') onImported(selected);
            else setJob(selected);
          }}>
            <option value="">Select a task</option>
            {jobs.map((item) => <option key={item.id} value={item.id}>{item.skin_name} · {item.status}</option>)}
          </select>
        </label>}
        <label className="field"><span>Prompt</span>
          <textarea rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)}
            placeholder="Describe the colors, materials and style you want" />
        </label>
        <label className="field"><span>Look name</span>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="emerald-robes" maxLength={48} />
        </label>
        <div className="muted">Method: {method === 'atlas' ? 'Atlas + snapshot' : 'Exploded parts'} · change in Settings</div>
        <div className="actions"><button className="primary" disabled={busy || !prompt.trim() || !name.trim()} onClick={prepare}>
          {busy ? 'Preparing…' : 'Prepare for Codex'}
        </button></div>
      </> : <>
        <div className="report">Waiting for image… · {job.skin_name}</div>
        <img className="handoff-input" src={api.fileUrl(job.input_image)} alt="Prepared image for Codex" />
        <label className="field"><span>Request for Codex</span><textarea readOnly rows={5} value={request} /></label>
        <div className="actions">
          <a href={api.fileUrl(job.input_image)} download="reskin-input.png">Download input</a>
          <button onClick={async () => {
            try { await navigator.clipboard.writeText(request); setCopied(true); }
            catch { setError('Select and copy the request above.'); }
          }}>{copied ? 'Copied' : 'Copy request'}</button>
        </div>
        <p className="muted">Codex can import directly; this preview updates automatically. You can also select its saved PNG, JPEG or WebP below. Keep the full {job.expected_size.join(' × ')} canvas.</p>
        <label className="field"><span>Generated image</span>
          <input type="file" accept="image/png,image/jpeg,image/webp" disabled={busy}
            onChange={(e) => { setImage(e.target.files?.[0] ?? null); setError(''); }} />
        </label>
        <div className="actions">
          <button disabled={busy} onClick={() => { setJob(null); setImage(null); setCopied(false); setError(''); }}>Back to tasks</button>
          <button className="primary" disabled={busy || !image} onClick={async () => {
            if (!image) return;
            setBusy(true); setError('');
            try { onImported(await api.importHandoff(job.id, image)); }
            catch (e) { setError((e as Error).message); }
            finally { setBusy(false); }
          }}>{busy ? 'Importing…' : 'Import image'}</button>
        </div>
      </>}
    </div>
  );
}
