import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles.scss';

const PAGE_BG = '#201E1E';
document.documentElement.classList.add('cds--g100');
document.body.classList.add('cds--g100');
document.documentElement.style.backgroundColor = PAGE_BG;
document.body.style.backgroundColor = PAGE_BG;
document.documentElement.style.colorScheme = 'dark';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
