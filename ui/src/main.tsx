import React from 'react';
import ReactDOM from 'react-dom/client';
import './lcca-polyfill';
import App from './App';
import './styles/reset.css';
import './styles/themes.css';  // UI-05 : variables dark/light — source de vérité thèmes
import './styles/globals.css';
import './styles/animations.css';  // UI-05 : fichier dédié animations
import './styles/components.css';
import './styles/ui02.css';
import './styles/ui03.css';
import './styles/ui04.css';
import './styles/ui05-enhancements.css';  // UI-05-ENH : améliorations UX/UI thèmes dual

const root = document.getElementById('root');
if (!root) throw new Error('Element #root introuvable dans index.html');

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
