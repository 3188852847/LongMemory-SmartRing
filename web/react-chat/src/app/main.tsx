import {createRoot} from 'react-dom/client';
import {ConsoleApp} from './ConsoleApp';
import '../styles/style.css';
import '../styles/shared-visual.css';

createRoot(document.getElementById('root')!).render(<ConsoleApp/>);
