import {createRoot} from 'react-dom/client';
import {ConsoleApp} from './ConsoleApp';
import {AmbientMotionToggle, DigitalAtmosphere} from '../components/DigitalAtmosphere';
import '../styles/style.css';
import '../styles/shared-visual.css';

createRoot(document.getElementById('root')!).render(<><DigitalAtmosphere/><ConsoleApp/><AmbientMotionToggle floating/></>);
