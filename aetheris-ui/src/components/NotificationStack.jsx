import { AnimatePresence, motion } from 'framer-motion';
import { CheckCircle2, AlertTriangle, XCircle, Info, X } from 'lucide-react';
import { useNotificationStore } from '../store/useNotificationStore';
import { useSettingsStore } from '../store/useSettingsStore';

const TYPE_CONFIG = {
  success: {
    icon: CheckCircle2,
    bgClass: 'bg-emerald-500/10',
    borderClass: 'border-emerald-400/20',
    textClass: 'text-emerald-300',
    iconClass: 'text-emerald-400',
  },
  warning: {
    icon: AlertTriangle,
    bgClass: 'bg-amber-500/10',
    borderClass: 'border-amber-400/20',
    textClass: 'text-amber-300',
    iconClass: 'text-amber-400',
  },
  error: {
    icon: XCircle,
    bgClass: 'bg-rose-500/10',
    borderClass: 'border-rose-400/20',
    textClass: 'text-rose-300',
    iconClass: 'text-rose-400',
  },
  info: {
    icon: Info,
    bgClass: 'bg-blue-500/10',
    borderClass: 'border-blue-400/20',
    textClass: 'text-blue-300',
    iconClass: 'text-blue-400',
  },
};

function NotificationToast({ notification, onDismiss }) {
  const config = TYPE_CONFIG[notification.type] || TYPE_CONFIG.info;
  const Icon = config.icon;
  const animationsEnabled = useSettingsStore((s) => s.animationsEnabled);

  return (
    <motion.div
      layout
      initial={animationsEnabled ? { x: '100%', opacity: 0 } : { x: 0, opacity: 1 }}
      animate={{ x: 0, opacity: 1 }}
      exit={animationsEnabled ? { x: '100%', opacity: 0 } : { x: 0, opacity: 0 }}
      transition={{ type: 'spring', stiffness: 300, damping: 28 }}
      className={`flex items-start gap-3 rounded-xl border p-3 backdrop-blur-xl ${config.bgClass} ${config.borderClass}`}
      role="alert"
    >
      <Icon className={`h-4 w-4 flex-shrink-0 mt-0.5 ${config.iconClass}`} aria-hidden="true" />
      <p className={`flex-1 text-sm ${config.textClass}`}>{notification.message}</p>
      {notification.dismissible && (
        <button
          onClick={() => onDismiss(notification.id)}
          aria-label="Dismiss notification"
          className="btn-icon touch-target flex-shrink-0 p-0.5"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      )}
    </motion.div>
  );
}

export default function NotificationStack() {
  const notifications = useNotificationStore((s) => s.notifications);
  const dismissNotification = useNotificationStore((s) => s.dismissNotification);

  return (
    <div
      aria-live="polite"
      aria-relevant="additions removals"
      className="fixed top-4 right-4 z-[60] flex flex-col gap-2 w-80 max-w-[calc(100vw-2rem)]"
    >
      <AnimatePresence mode="popLayout">
        {notifications.map((notification) => (
          <NotificationToast
            key={notification.id}
            notification={notification}
            onDismiss={dismissNotification}
          />
        ))}
      </AnimatePresence>
    </div>
  );
}
