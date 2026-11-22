import * as React from 'react';
import { X, CheckCircle2, AlertCircle, AlertTriangle, Info } from 'lucide-react';
import { cn } from '../../lib/utils';

export interface Toast {
  id: string;
  title?: string;
  description?: string;
  type?: 'success' | 'error' | 'warning' | 'info';
  duration?: number;
}

interface ToastProps extends Toast {
  onClose: (id: string) => void;
}

const Toast: React.FC<ToastProps> = ({ id, title, description, type = 'info', onClose }) => {
  const typeConfig = {
    success: {
      icon: CheckCircle2,
      iconColor: 'text-emerald-500'
    },
    error: {
      icon: AlertCircle,
      iconColor: 'text-red-500'
    },
    warning: {
      icon: AlertTriangle,
      iconColor: 'text-amber-500'
    },
    info: {
      icon: Info,
      iconColor: 'text-blue-500'
    },
  };

  const config = typeConfig[type];
  const Icon = config.icon;

  return (
    <div
      className={cn(
        'pointer-events-auto w-full max-w-md overflow-hidden rounded-lg',
        'bg-[#1a1a1a] border border-white/10',
        'shadow-lg',
        'animate-in slide-in-from-top-2 fade-in-0 duration-300'
      )}
    >
      <div className="p-3.5">
        <div className="flex items-start gap-3">
          {/* Icon simple */}
          <div className={cn('flex-shrink-0 mt-0.5', config.iconColor)}>
            <Icon className="h-4 w-4" strokeWidth={2} />
          </div>

          {/* Contenu */}
          <div className="flex-1 min-w-0">
            {title && (
              <p className="font-medium text-[13px] text-white mb-0.5">
                {title}
              </p>
            )}
            {description && (
              <p className="text-[13px] text-white/70 leading-relaxed">
                {description}
              </p>
            )}
          </div>

          {/* Bouton fermer */}
          <button
            onClick={() => onClose(id)}
            className={cn(
              'flex-shrink-0 rounded p-1 transition-colors',
              'text-white/40 hover:text-white/70 hover:bg-white/5',
              'focus:outline-none'
            )}
            aria-label="Fermer"
          >
            <X className="h-3.5 w-3.5" strokeWidth={2} />
          </button>
        </div>
      </div>
    </div>
  );
};

export { Toast };
