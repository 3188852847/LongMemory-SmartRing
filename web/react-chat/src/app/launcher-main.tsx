import {createRoot} from 'react-dom/client';
import {AppearanceProvider} from './AppearanceProvider';
import {DigitalAtmosphere} from '../components/DigitalAtmosphere';
import {LauncherApp} from '../features/launcher/LauncherApp';
import {consumeLauncherToken, LauncherApi} from '../features/launcher/api';
import '../styles/style.css';
import '../styles/shared-visual.css';
import '../styles/launcher.css';

const api = new LauncherApi(consumeLauncherToken(window.location, window.history));
createRoot(document.getElementById('root')!).render(<AppearanceProvider><DigitalAtmosphere launcher/><LauncherApp api={api}/></AppearanceProvider>);
