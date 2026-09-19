import { useState, useEffect } from 'react';
import { TopBar } from './components/TopBar';
import { Sidebar } from './components/Sidebar';
import { SpineCanvas } from './components/canvas/SpineCanvas';
import { PartEditor } from './components/right-panel/PartEditor';
import { GlobalGenerateModal } from './components/modals/GlobalGenerateModal';
import { SettingsModal } from './components/modals/SettingsModal';
import { ProjectPickerModal } from './components/modals/ProjectPickerModal';
import { LogsModal } from './components/modals/LogsModal';
import { KeyPromptModal } from './components/modals/KeyPromptModal';
import { ExportModal } from './components/modals/ExportModal';
import { api, isMultiProjectChoice, type MultiProjectChoice } from './api/client';
import { useStore } from './state/store';
import './styles/index.css';

export function App() {
  const project = useStore((s) => s.project);
  const setProject = useStore((s) => s.setProject);
  const refreshSecrets = useStore((s) => s.refreshSecrets);
  const keyPrompt = useStore((s) => s.keyPrompt);
  const setKeyPrompt = useStore((s) => s.setKeyPrompt);
  const [generateOpen, setGenerateOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [logsOpen, setLogsOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [pickerChoice, setPickerChoice] = useState<MultiProjectChoice | null>(null);

  // Restore the open project (if any) + load saved API-key status on mount
  useEffect(() => {
    api.getStatus().then((s) => {
      if (s.open && s.path && s.slots) {
        setProject(s as any);
      }
    });
    refreshSecrets();
  }, [setProject, refreshSecrets]);

  const onOpen = async () => {
    const path = window.prompt(
      'Path to a Spine project folder',
      '/Users/yotamwolf/Downloads/spine_project_duckies/spine_test/benny',
    );
    if (!path) return;
    try {
      const r = await api.openProject(path);
      if (isMultiProjectChoice(r)) {
        setPickerChoice(r);
        return;
      }
      setProject(r);
    } catch (e) {
      alert(`open failed: ${(e as Error).message}`);
    }
  };

  return (
    <div className="app">
      <TopBar
        onOpen={onOpen}
        onGenerate={() => setGenerateOpen(true)}
        onSettings={() => setSettingsOpen(true)}
        onLogs={() => setLogsOpen(true)}
        onExport={() => setExportOpen(true)}
        exporting={false}
      />

      <SpineCanvas />
      <Sidebar />
      <PartEditor />

      {exportOpen && project && <ExportModal key={project.path} onClose={() => setExportOpen(false)} />}
      {generateOpen && project && (
        <GlobalGenerateModal key={project.path} onClose={() => setGenerateOpen(false)} />
      )}
      {settingsOpen && (
        <SettingsModal onClose={() => { setSettingsOpen(false); refreshSecrets(); }} />
      )}
      {logsOpen && (
        <LogsModal onClose={() => setLogsOpen(false)} />
      )}
      {pickerChoice && (
        <ProjectPickerModal
          choice={pickerChoice}
          onResolved={(p) => { setProject(p); setPickerChoice(null); }}
          onClose={() => setPickerChoice(null)}
        />
      )}
      {keyPrompt && (
        <KeyPromptModal
          prompt={keyPrompt}
          onClose={() => setKeyPrompt(null)}
          onOpenSettings={() => { setKeyPrompt(null); setSettingsOpen(true); }}
        />
      )}
    </div>
  );
}
