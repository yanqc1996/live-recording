import { useEffect } from 'react';

export function canLeaveEditor() {
  return window.dispatchEvent(new Event('editor-before-leave', { cancelable: true }));
}

export function useUnsavedChanges(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
    const leave = (event: Event) => {
      if (!window.confirm('有未保存的修改。确定离开？\n取消可留在当前页面继续编辑或保存。')) event.preventDefault();
    };
    const unload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('editor-before-leave', leave);
    window.addEventListener('beforeunload', unload);
    return () => {
      window.removeEventListener('editor-before-leave', leave);
      window.removeEventListener('beforeunload', unload);
    };
  }, [dirty]);
}
