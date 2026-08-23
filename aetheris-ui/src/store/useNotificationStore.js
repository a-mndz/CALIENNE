import { create } from 'zustand';

function createId() {
  return typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `notif-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

const AUTO_DISMISS_MS = 5000;

export const useNotificationStore = create((set, get) => ({
  notifications: [],

  addNotification: (notification) => {
    const id = createId();
    const entry = {
      id,
      type: notification.type || 'info',
      message: notification.message,
      duration: notification.duration ?? AUTO_DISMISS_MS,
      dismissible: notification.dismissible ?? true,
      timestamp: Date.now(),
    };

    set((state) => ({
      notifications: [...state.notifications, entry],
    }));

    if (entry.duration > 0 && entry.type !== 'error') {
      setTimeout(() => {
        get().dismissNotification(id);
      }, entry.duration);
    }

    return id;
  },

  dismissNotification: (id) => {
    set((state) => ({
      notifications: state.notifications.filter((n) => n.id !== id),
    }));
  },

  clearAll: () => {
    set({ notifications: [] });
  },

  success: (message, opts) => get().addNotification({ type: 'success', message, ...opts }),
  warning: (message, opts) => get().addNotification({ type: 'warning', message, ...opts }),
  error: (message, opts) => get().addNotification({ type: 'error', message, ...opts }),
  info: (message, opts) => get().addNotification({ type: 'info', message, ...opts }),
}));
