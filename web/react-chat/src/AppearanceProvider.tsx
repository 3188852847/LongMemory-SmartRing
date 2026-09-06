import {createContext, type ReactNode, useContext, useEffect, useMemo, useState} from 'react';
import {ConfigProvider, theme} from 'antd';
import {KEY, normalize, read, save, apply} from '../../assets/appearance.mjs';

type ThemePreference = 'system' | 'light' | 'dark';
type ReadingSize = 'normal' | 'large' | 'larger';
export type AppearancePreferences = {theme: ThemePreference; size: ReadingSize};
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

  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)');
    const onMedia = () => setSystemDark(media.matches);
    const onStorage = (event: StorageEvent) => {
      if (event.key === KEY || event.key === null) setPrefs(safeRead());
    };
    media.addEventListener('change', onMedia);
    window.addEventListener('storage', onStorage);
    return () => {
      media.removeEventListener('change', onMedia);
      window.removeEventListener('storage', onStorage);
    };
  }, []);

  useEffect(() => {apply(document.documentElement, prefs, systemDark);}, [prefs, systemDark]);

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

  const dark = prefs.theme === 'dark' || (prefs.theme === 'system' && systemDark);
  const fontSize = prefs.size === 'larger' ? 20 : prefs.size === 'large' ? 18 : 16;
  return <AppearanceContext.Provider value={value}>
    <ConfigProvider csp={{nonce}} theme={{algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
      token: {colorPrimary: '#b62e68', fontSize, borderRadius: 10}}}>
      {children}
    </ConfigProvider>
  </AppearanceContext.Provider>;
}

export function useAppearance() {
  const value = useContext(AppearanceContext);
  if (!value) throw new Error('useAppearance 必须在 AppearanceProvider 内使用');
  return value;
}
