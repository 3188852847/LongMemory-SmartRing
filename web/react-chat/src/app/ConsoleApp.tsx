import {lazy, Suspense} from 'react';
import {QueryClientProvider} from '@tanstack/react-query';
import {BrowserRouter, Navigate, Route, Routes} from 'react-router-dom';
import {AppearanceProvider} from './AppearanceProvider';
import {createConsoleQueryClient} from './queryClient';
import {ChatApp} from '../pages/ChatApp';
import '../styles/workspace-shell.css';

const DeviceApp = lazy(() => import('../pages/DeviceApp').then(module => ({default: module.DeviceApp})));
const MemoryApp = lazy(() => import('../pages/MemoryApp').then(module => ({default: module.MemoryApp})));
const MemoryQualityApp = lazy(() => import('../pages/MemoryQualityApp').then(module => ({default: module.MemoryQualityApp})));
const ScenarioApp = lazy(() => import('../pages/ScenarioApp').then(module => ({default: module.ScenarioApp})));
const PersonaApp = lazy(() => import('../pages/PersonaApp').then(module => ({default: module.PersonaApp})));
const SettingsApp = lazy(() => import('../pages/SettingsApp').then(module => ({default: module.SettingsApp})));
const ExperimentApp = lazy(() => import('../pages/ExperimentApp').then(module => ({default: module.ExperimentApp})));
const RoundDisplayApp = lazy(() => import('../pages/RoundDisplayApp').then(module => ({default: module.RoundDisplayApp})));
const OverviewApp = lazy(() => import('../pages/OverviewApp').then(module => ({default: module.OverviewApp})));

const queryClient = createConsoleQueryClient();

/** 应用装配层只建立共享上下文和路由，具体交互由页面与业务功能负责。 */
export function ConsoleApp() {
  return <QueryClientProvider client={queryClient}><AppearanceProvider><BrowserRouter><Routes>
    <Route path="/overview" element={<Suspense fallback={<p className="page-loading">正在加载系统总览…</p>}><OverviewApp/></Suspense>}/>
    <Route path="/device" element={<Suspense fallback={<p className="page-loading">正在加载设备控制…</p>}><DeviceApp/></Suspense>}/>
    <Route path="/display-preview" element={<Suspense fallback={<p className="page-loading">正在加载圆屏预览…</p>}><RoundDisplayApp/></Suspense>}/>
    <Route path="/chat-react" element={<ChatApp/>}/>
    <Route path="/memories" element={<Suspense fallback={<p className="page-loading">正在加载记忆管理…</p>}><MemoryApp/></Suspense>}/>
    <Route path="/memory-quality" element={<Suspense fallback={<p className="page-loading">正在加载记忆质量样本…</p>}><MemoryQualityApp/></Suspense>}/>
    <Route path="/scenarios" element={<Suspense fallback={<p className="page-loading">正在加载生活场景…</p>}><ScenarioApp/></Suspense>}/>
    <Route path="/personas" element={<Suspense fallback={<p className="page-loading">正在加载用户画像…</p>}><PersonaApp/></Suspense>}/>
    <Route path="/settings" element={<Suspense fallback={<p className="page-loading">正在加载个性化设置…</p>}><SettingsApp/></Suspense>}/>
    <Route path="/experiments-react" element={<Suspense fallback={<p className="page-loading">正在加载实验档案…</p>}><ExperimentApp/></Suspense>}/>
    <Route path="*" element={<Navigate to="/chat-react" replace/>}/>
  </Routes></BrowserRouter></AppearanceProvider></QueryClientProvider>;
}
