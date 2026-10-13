import {render, screen, fireEvent} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import {DiagnosticsPanel} from './DiagnosticsPanel';
import type {DiagnosticSnapshot} from './types';

const snapshot: DiagnosticSnapshot = {
  schema_version: 1, scope: 'current_process', capacity: 100, persistence: 'enabled',
  device_playback: 'unconfirmed', coverage: [], uncovered: [], logs: [],
  requests: [{request_id: 'a'.repeat(24), time: '2026-10-14T00:00:00Z', operation: 'device',
    stage: 'request', outcome: 'unknown', code: 'bridge_timeout', status: 504, duration_ms: 18,
    stages: []}],
};

describe('安全故障摘要', () => {
  it('保留执行结果未知和设备播放未确认，刷新只读摘要', () => {
    const refresh = vi.fn();
    render(<DiagnosticsPanel snapshot={snapshot} onRefresh={refresh}/>);
    expect(screen.getByText('执行结果未知，请重新读取状态')).toBeTruthy();
    expect(screen.getByText(/设备播放仍未确认/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', {name: '刷新摘要'}));
    expect(refresh).toHaveBeenCalledOnce();
  });
  it('错误可被辅助技术读取，同时保留上次摘要', () => {
    render(<DiagnosticsPanel snapshot={snapshot} error onRefresh={() => {}}/>);
    expect(screen.getByRole('alert').textContent).toContain('摘要暂不可读取');
    expect(screen.getByText('执行结果未知，请重新读取状态')).toBeTruthy();
  });
  it('空状态明确重启历史未加载', () => {
    render(<DiagnosticsPanel snapshot={{...snapshot, requests: []}} onRefresh={() => {}}/>);
    expect(screen.getByText(/重启前记录未加载/)).toBeTruthy();
  });
});
