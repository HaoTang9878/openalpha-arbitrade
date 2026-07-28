/**
 * Toast 通知组件
 *
 * 替代原生 alert()，提供 success/error/warning/info 四种类型。
 * 使用 Zustand 管理通知队列，自动消失（可配置时长），
 * 支持手动关闭。固定在右上角，堆叠显示。
 *
 * 使用方法：
 *   import { toast } from './Toast';
 *   toast.success('保存成功');
 *   toast.error('操作失败: ' + err.message);
 */

import { create } from 'zustand';


type ToastType = 'success' | 'error' | 'warning' | 'info';

interface ToastItem {
  id: number;
  type: ToastType;
  message: string;
  duration: number;
}

interface ToastStore {
  toasts: ToastItem[];
  addToast: (type: ToastType, message: string, duration?: number) => void;
  removeToast: (id: number) => void;
}

let toastId = 0;

/** Toast 状态管理 */
const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  addToast: (type, message, duration = 3000) => {
    const id = ++toastId;
    set((state) => ({
      toasts: [...state.toasts, { id, type, message, duration }],
    }));
    // 自动消失
    setTimeout(() => {
      set((state) => ({
        toasts: state.toasts.filter((t) => t.id !== id),
      }));
    }, duration);
  },
  removeToast: (id) =>
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    })),
}));

/** Toast API（全局调用） */
export const toast = {
  success: (msg: string, duration?: number) =>
    useToastStore.getState().addToast('success', msg, duration),
  error: (msg: string, duration?: number) =>
    useToastStore.getState().addToast('error', msg, duration ?? 5000),
  warning: (msg: string, duration?: number) =>
    useToastStore.getState().addToast('warning', msg, duration),
  info: (msg: string, duration?: number) =>
    useToastStore.getState().addToast('info', msg, duration),
};

/** Toast 类型 → 样式映射 */
const TOAST_STYLES: Record<ToastType, { bg: string; border: string; icon: string }> = {
  success: { bg: 'rgba(14,203,129,0.12)', border: 'var(--color-up)', icon: '✓' },
  error: { bg: 'rgba(246,70,93,0.12)', border: 'var(--color-down)', icon: '✕' },
  warning: { bg: 'rgba(251,191,36,0.12)', border: 'var(--color-warning)', icon: '⚠' },
  info: { bg: 'rgba(33,150,243,0.12)', border: 'var(--color-info)', icon: 'ℹ' },
};

/** 单个 Toast 项 */
function ToastItemView({ toast, onClose }: { toast: ToastItem; onClose: () => void }) {
  const style = TOAST_STYLES[toast.type];
  return (
    <div
      className="flex items-start gap-2.5 px-4 py-3 rounded-lg shadow-md min-w-[280px] max-w-[400px] animate-slide-in-right"
      style={{
        backgroundColor: style.bg,
        borderLeft: `3px solid ${style.border}`,
        backdropFilter: 'blur(8px)',
      }}
    >
      <span className="text-base font-bold flex-shrink-0" style={{ color: style.border }}>
        {style.icon}
      </span>
      <span className="text-sm flex-1" style={{ color: 'var(--color-text-primary)' }}>
        {toast.message}
      </span>
      <button
        onClick={onClose}
        className="text-xs opacity-50 hover:opacity-100 flex-shrink-0"
        style={{ color: 'var(--color-text-muted)' }}
      >
        ✕
      </button>
    </div>
  );
}

/** Toast 容器（固定在右上角） */
export function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts);
  const removeToast = useToastStore((s) => s.removeToast);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-2">
      {toasts.map((t) => (
        <ToastItemView key={t.id} toast={t} onClose={() => removeToast(t.id)} />
      ))}
    </div>
  );
}
