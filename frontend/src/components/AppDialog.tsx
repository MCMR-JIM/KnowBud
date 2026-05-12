import { createContext, useCallback, useContext, useState } from 'react';
import type { ReactNode } from 'react';

type DialogIntent = 'info' | 'success' | 'warning' | 'error' | 'danger';

type DialogOptions = {
  title?: string;
  intent?: DialogIntent;
  confirmText?: string;
  cancelText?: string;
};

type DialogRequest = Required<Pick<DialogOptions, 'title' | 'intent' | 'confirmText' | 'cancelText'>> & {
  message: string;
  mode: 'alert' | 'confirm';
  resolve: (value: boolean) => void;
};

type AppDialogApi = {
  alert: (message: string, options?: DialogOptions) => Promise<void>;
  confirm: (message: string, options?: DialogOptions) => Promise<boolean>;
};

const AppDialogContext = createContext<AppDialogApi | null>(null);

const intentStyles: Record<DialogIntent, { badge: string; button: string; icon: string }> = {
  info: { badge: 'bg-sky-50 text-sky-600 border-sky-100', button: 'bg-slate-900 hover:bg-sky-600', icon: 'i' },
  success: { badge: 'bg-emerald-50 text-emerald-600 border-emerald-100', button: 'bg-emerald-600 hover:bg-emerald-700', icon: '✓' },
  warning: { badge: 'bg-amber-50 text-amber-600 border-amber-100', button: 'bg-amber-500 hover:bg-amber-600', icon: '!' },
  error: { badge: 'bg-rose-50 text-rose-600 border-rose-100', button: 'bg-rose-600 hover:bg-rose-700', icon: '!' },
  danger: { badge: 'bg-red-50 text-red-600 border-red-100', button: 'bg-red-600 hover:bg-red-700', icon: '!' },
};

function defaultTitle(intent: DialogIntent) {
  if (intent === 'success') return '操作成功';
  if (intent === 'warning') return '需要注意';
  if (intent === 'error') return '操作失败';
  if (intent === 'danger') return '确认危险操作';
  return '提示';
}

export function AppDialogProvider({ children }: { children: ReactNode }) {
  const [dialog, setDialog] = useState<DialogRequest | null>(null);

  const openDialog = useCallback((mode: 'alert' | 'confirm', message: string, options: DialogOptions = {}) => {
    const intent = options.intent || (mode === 'confirm' ? 'warning' : 'info');
    return new Promise<boolean>((resolve) => {
      setDialog({
        mode,
        message,
        resolve,
        intent,
        title: options.title || defaultTitle(intent),
        confirmText: options.confirmText || (mode === 'confirm' ? '确认' : '知道了'),
        cancelText: options.cancelText || '取消',
      });
    });
  }, []);

  const alert = useCallback(async (message: string, options?: DialogOptions) => {
    await openDialog('alert', message, options);
  }, [openDialog]);

  const confirm = useCallback((message: string, options?: DialogOptions) => {
    return openDialog('confirm', message, options);
  }, [openDialog]);

  const closeDialog = (value: boolean) => {
    const current = dialog;
    setDialog(null);
    current?.resolve(value);
  };

  const styles = dialog ? intentStyles[dialog.intent] : intentStyles.info;

  return (
    <AppDialogContext.Provider value={{ alert, confirm }}>
      {children}
      {dialog && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md overflow-hidden rounded-[28px] border border-white/70 bg-white shadow-2xl">
            <div className="relative overflow-hidden p-6">
              <div className="absolute -right-10 -top-12 h-32 w-32 rounded-full bg-pink-200/40 blur-3xl"></div>
              <div className="relative flex items-start gap-4">
                <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border text-xl font-black ${styles.badge}`}>
                  {styles.icon}
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="text-lg font-black text-gray-900">{dialog.title}</h2>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-600">{dialog.message}</p>
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-3 border-t border-gray-100 bg-gray-50 px-6 py-4">
              {dialog.mode === 'confirm' && (
                <button
                  type="button"
                  onClick={() => closeDialog(false)}
                  className="rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-bold text-gray-600 transition-colors hover:bg-gray-100"
                >
                  {dialog.cancelText}
                </button>
              )}
              <button
                type="button"
                onClick={() => closeDialog(true)}
                className={`rounded-xl px-5 py-2 text-sm font-black text-white shadow-lg shadow-gray-200 transition-colors ${styles.button}`}
              >
                {dialog.confirmText}
              </button>
            </div>
          </div>
        </div>
      )}
    </AppDialogContext.Provider>
  );
}

export function useAppDialog() {
  const context = useContext(AppDialogContext);
  if (!context) throw new Error('useAppDialog must be used inside AppDialogProvider');
  return context;
}
