import {createContext, type ReactNode, useContext, useEffect, useMemo, useState} from 'react';
import {ConfigProvider, theme} from 'antd';
import {KEY, normalize, read, save, apply} from '../../../assets/appearance.mjs';

type ThemePreference = 'system' | 'light' | 'dark' | 'future';
type ReadingSize = 'normal' | 'large' | 'larger';
type MotionPreference = 'system' | 'reduce' | 'full';
type DensityPreference = 'comfortable' | 'compact';
type ChatWidthPreference = 'focused' | 'wide';
export type AppearancePreferences = {
  theme: ThemePreference; size: ReadingSize; motion: MotionPreference;
  density: DensityPreference; chatWidth: ChatWidthPreference;
};
type AppearanceContextValue = {
  prefs: AppearancePreferences;
  update: (next: AppearancePreferences) => boolean;
  reset: () => boolean;
};

const AppearanceContext = createContext<AppearanceContextValue | null>(null);
const nonce = document.querySelector<HTMLMetaElement>('meta[name="style-nonce"]')?.content;

function safeRead(): AppearancePreferences {
  try {return read(localStorage) as AppearancePreferences;}
  catch {return normalize(null) as AppearancePreferences;}
}

/** 统一聊天页和记忆页的主题状态，避免两个入口各自维护一份监听逻辑。 */
export function AppearanceProvider({children}: {children: ReactNode}) {
  const [prefs, setPrefs] = useState<AppearancePreferences>(safeRead);
  const [systemDark, setSystemDark] = useState(() => matchMedia('(prefers-color-scheme: dark)').matches);
  const [systemReducedMotion, setSystemReducedMotion] = useState(
    () => matchMedia('(prefers-reduced-motion: reduce)').matches,
  );

  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)');
    const motionMedia = matchMedia('(prefers-reduced-motion: reduce)');
    const onMedia = () => setSystemDark(media.matches);
    const onMotionMedia = () => setSystemReducedMotion(motionMedia.matches);
    const onStorage = (event: StorageEvent) => {
      if (event.key === KEY || event.key === null) setPrefs(safeRead());
    };
    media.addEventListener('change', onMedia);
    motionMedia.addEventListener('change', onMotionMedia);
    window.addEventListener('storage', onStorage);
    return () => {
      media.removeEventListener('change', onMedia);
      motionMedia.removeEventListener('change', onMotionMedia);
      window.removeEventListener('storage', onStorage);
    };
  }, []);

  useEffect(() => {
    apply(document.documentElement, prefs, systemDark, systemReducedMotion);
  }, [prefs, systemDark, systemReducedMotion]);

  useEffect(() => {
    // 键盘不等待装饰过渡；选择器只影响视觉，不阻止任何事件或修改焦点。
    const onKey = () => {document.documentElement.dataset.inputModality = 'keyboard';};
    const onPointer = () => {document.documentElement.dataset.inputModality = 'pointer';};
    window.addEventListener('keydown', onKey, true);
    window.addEventListener('pointerdown', onPointer, true);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      window.removeEventListener('pointerdown', onPointer, true);
    };
  }, []);

  const value = useMemo<AppearanceContextValue>(() => ({
    prefs,
    update(next) {
      const normalized = normalize(next) as AppearancePreferences;
      setPrefs(normalized);
      try {return Boolean(save(localStorage, normalized));} catch {return false;}
    },
    reset() {
      const defaults = normalize(null) as AppearancePreferences;
      setPrefs(defaults);
      try {return Boolean(save(localStorage, defaults));} catch {return false;}
    },
  }), [prefs]);

  const future = prefs.theme === 'future';
  const dark = future || prefs.theme === 'dark' || (prefs.theme === 'system' && systemDark);
  const fontSize = prefs.size === 'larger' ? 20 : prefs.size === 'large' ? 18 : 16;
  // Drawer/Modal 经 Portal 挂到 body，必须在组件库层关闭运动，不能只靠页面 CSS。
  const motion = !(prefs.motion === 'reduce' || (prefs.motion === 'system' && systemReducedMotion));
  return <AppearanceContext.Provider value={value}>
    <ConfigProvider csp={{nonce}} theme={{algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
      token: {
        motion,
        colorPrimary: future ? '#5ce5ed' : dark ? '#e16e9e' : '#a72a5f',
        colorInfo: future ? '#55a7ff' : dark ? '#74a0df' : '#3769b0',
        colorSuccess: future ? '#70dfbd' : dark ? '#55b889' : '#198754',
        colorWarning: future ? '#efb864' : dark ? '#d6a94e' : '#b7791f',
        colorError: future ? '#ff8395' : dark ? '#e06b75' : '#c43d4b',
        colorBgLayout: future ? '#06111b' : dark ? '#101217' : '#f5f6f8',
        colorBgContainer: future ? '#0b1c2c' : dark ? '#171a21' : '#ffffff',
        colorBgElevated: future ? '#102738' : dark ? '#1b1f27' : '#ffffff',
        colorBorderSecondary: future ? '#173b58' : dark ? '#2a2f39' : '#e3e6eb',
        colorText: future ? '#edf7fb' : dark ? '#e7eaf0' : '#20232b',
        colorTextSecondary: future ? '#a2bac9' : dark ? '#9da5b3' : '#6b7280',
        fontFamily: 'Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif',
        fontSize,
        borderRadius: 8,
        borderRadiusLG: 12,
        motionDurationFast: '0.1s', motionDurationMid: '0.16s', motionDurationSlow: '0.24s',
        motionEaseOut: 'cubic-bezier(0.23, 1, 0.32, 1)',
        controlHeight: 36,
        boxShadow: future ? '0 18px 42px rgba(0,0,0,.28)' : dark ? '0 12px 32px rgba(0,0,0,.2)' : '0 8px 28px rgba(17,24,39,.055)',
      },
      components: {
        Button: {primaryShadow: 'none', defaultShadow: 'none', dangerShadow: 'none'},
        Card: {headerBg: 'transparent'},
        Drawer: {colorBgElevated: future ? '#0b1c2c' : dark ? '#171a21' : '#ffffff'},
        Modal: {contentBg: future ? '#0b1c2c' : dark ? '#171a21' : '#ffffff', headerBg: future ? '#0b1c2c' : dark ? '#171a21' : '#ffffff'},
      },
    }}>
      {children}
    </ConfigProvider>
  </AppearanceContext.Provider>;
}

export function useAppearance() {
  const value = useContext(AppearanceContext);
  if (!value) throw new Error('useAppearance 必须在 AppearanceProvider 内使用');
  return value;
}
