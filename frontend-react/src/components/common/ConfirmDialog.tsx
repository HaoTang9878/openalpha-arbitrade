/**
 * 确认对话框组件
 *
 * 替代原生 confirm()，提供可定制的 Modal 对话框。
 * 使用 Zustand 管理对话框状态，支持 Promise 异步确认。
 *
 * 使用方法：
 *   import { confirm } from './ConfirmDialog';
 *   if (await confirm('确认执行套利？', { okText: '执行', cancelText: '取消' })) {
 *     await api.executeTrade(opp);
 *   }
 */

import { create } from 'zustand';
import { useCallback } from 'react';

interface ConfirmOptions {
  title?: string;
  okText?: string;
  cancelText?: string;
  okType?: 'primary' | 'danger';
}

interface ConfirmState {
  visible: boolean;
  message: string;
  options: ConfirmOptions;
  resolve?: (value: boolean) => void;
  show: (message: string, options?: ConfirmOptions) => Promise<boolean>;
  hide: (result: boolean) => void;
}

const useConfirmStore = create<ConfirmState>((set) => ({
  visible: false,
  message: '',
  options: {},
  resolve: undefined,
  show: (message, options = {}) => {
    return new Promise<boolean>((resolve) => {
      set({ visible: true, message, options, resolve });
    });
  },
  hide: (result) => {
    set((state) => {
      state.resolve?.(result);
      return { visible: false, resolve: undefined };
    });
  },
}));

/** 确认对话框 API（返回 Promise<boolean>） */
export const confirm = (message: string, options?: ConfirmOptions) =>
  useConfirmStore.getState().show(message, options);

/** 确认对话框组件 */
export function ConfirmDialog() {
  const { visible, message, options, hide } = useConfirmStore();

  const handleOk = useCallback(() => hide(true), [hide]);
  const handleCancel = useCallback(() => hide(false), [hide]);

  if (!visible) return null;

  const okText = options.okText || '确认';
  const cancelText = options.cancelText || '取消';
  const okClass = options.okType === 'danger' ? 'btn-danger' : 'btn-primary';

  return (
    <div
      className="fixed inset-0 z-[9998] flex items-center justify-center"
      style={{ backgroundColor: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }}
      onClick={handleCancel}
    >
      <div
        className="panel max-w-md w-full mx-4 animate-slide-up"
        style={{ boxShadow: 'var(--shadow-lg)' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* 标题 */}
        {options.title && (
          <div className="panel-header">
            <span className="panel-title">{options.title}</span>
          </div>
        )}
        {/* 内容 */}
        <div className="p-5">
          <p className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
            {message}
          </p>
        </div>
        {/* 按钮 */}
        <div className="flex justify-end gap-2 px-5 pb-5">
          <button className="btn btn-secondary btn-sm" onClick={handleCancel}>
            {cancelText}
          </button>
          <button className={`btn ${okClass} btn-sm`} onClick={handleOk}>
            {okText}
          </button>
        </div>
      </div>
    </div>
  );
}
