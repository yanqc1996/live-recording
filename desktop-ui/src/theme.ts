import { createTheme, type CSSVariablesResolver } from '@mantine/core';

const surfaces = {
  '--mantine-color-text': 'var(--text)',
  '--mantine-color-dimmed': 'var(--muted)',
  '--mantine-color-body': 'var(--app-bg)',
  '--mantine-color-default': 'var(--panel)',
  '--mantine-color-default-color': 'var(--text)',
  '--mantine-color-default-hover': 'var(--soft)',
  '--mantine-color-default-border': 'var(--line)',
};

export const workspaceCssVariables: CSSVariablesResolver = () => ({ variables: {}, light: surfaces, dark: surfaces });

export const workspaceTheme = createTheme({
  fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif',
  headings: { fontFamily: 'inherit', fontWeight: '650' },
  fontSizes: { xs: '0.75rem', sm: '0.8125rem', md: '0.875rem', lg: '1rem', xl: '1.25rem' },
  defaultRadius: 'md',
  radius: { xs: '0.25rem', sm: '0.375rem', md: '0.5rem', lg: '0.75rem', xl: '1rem' },
  primaryColor: 'blue',
  primaryShade: { light: 6, dark: 5 },
  colors: {
    dark: ['#e5edf7', '#c4cedc', '#9aa8bc', '#718198', '#48576d', '#344157', '#243044', '#182231', '#111a27', '#0d1420'],
  },
  components: {
    Button: { defaultProps: { radius: 'md', size: 'sm' } },
    ActionIcon: { defaultProps: { radius: 'md' } },
    TextInput: { defaultProps: { size: 'sm', radius: 'md' } },
    PasswordInput: { defaultProps: { size: 'sm', radius: 'md' } },
    Textarea: { defaultProps: { size: 'sm', radius: 'md' } },
    Select: { defaultProps: { size: 'sm', radius: 'md' } },
    NumberInput: { defaultProps: { size: 'sm', radius: 'md' } },
    Tooltip: { defaultProps: { openDelay: 350, withArrow: true } },
    Modal: { defaultProps: { radius: 'lg', overlayProps: { backgroundOpacity: 0.45, blur: 3 } } },
    Drawer: { defaultProps: { overlayProps: { backgroundOpacity: 0.35, blur: 2 } } },
  },
});
