import '@mantine/core/styles.css';
import './styles.css';
import './polish.css';
import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import { App } from './App';
import { MiniControls } from './MiniControls';
import { workspaceCssVariables, workspaceTheme } from './theme';

const mini = new URLSearchParams(location.search).get('mini') === '1';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><MantineProvider theme={workspaceTheme} cssVariablesResolver={workspaceCssVariables} defaultColorScheme="dark">{mini ? <MiniControls /> : <App />}</MantineProvider></React.StrictMode>,
);
