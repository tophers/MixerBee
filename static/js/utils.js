// static/js/utils.js

export const toastHistory = [];
const MAX_VISIBLE_TOASTS = 3;

export function generateUUID() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return ([1e7] + -1e3 + -4e3 + -8e3 + -1e11).replace(/[018]/g, c =>
    (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16)
  );
}

export function toast(message, isSuccess, options = {}) {
  const { actionCallback, actionText = 'View', actionIcon, duration } = options;

  const timestamp = new Date().toLocaleTimeString([], {
    hour: '2-digit', minute: '2-digit', second: '2-digit'
  });

  toastHistory.unshift({ message, isSuccess, timestamp });
  if (toastHistory.length > 50) toastHistory.pop();

  document.dispatchEvent(new CustomEvent('toast-added'));

  let stack = document.getElementById('toast-stack');
  if (!stack) {
    stack = document.createElement('div');
    stack.id = 'toast-stack';
    stack.setAttribute('role', 'status');
    stack.setAttribute('aria-live', 'polite');
    document.body.appendChild(stack);
  }
  // Keep the newest few visible instead of replacing the previous message outright.
  const live = stack.querySelectorAll('.toast:not(.leaving)');
  if (live.length >= MAX_VISIBLE_TOASTS) live[0].remove();

  const toastElement = document.createElement('div');
  toastElement.className = `toast ${isSuccess ? 'ok' : 'fail'}`;
  if (!isSuccess) toastElement.setAttribute('role', 'alert');

  let dismissTimer = null;
  const dismissToast = () => {
    clearTimeout(dismissTimer);
    if (toastElement.classList.contains('leaving')) return;
    toastElement.classList.add('leaving');
    toastElement.addEventListener('animationend', () => toastElement.remove(), { once: true });
    // Fallback when animations are disabled (reduced motion).
    setTimeout(() => toastElement.remove(), 500);
  };

  const messageDiv = document.createElement('div');
  messageDiv.className = 'toast-message';
  messageDiv.textContent = String(message ?? '');
  toastElement.appendChild(messageDiv);

  if (actionCallback) {
    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'toast-actions';
    const actionBtn = document.createElement('button');
    actionBtn.type = 'button';
    actionBtn.className = 'toast-button align-center gap-xs';

    const icon = actionIcon === null ? '' : (typeof Alpine !== 'undefined' ? Alpine.store('icons')?.[actionIcon || 'externalLink'] : '');
    if (icon) {
      const iconSpan = document.createElement('span');
      iconSpan.className = 'toast-button-icon';
      iconSpan.innerHTML = icon;
      actionBtn.appendChild(iconSpan);
    }

    actionBtn.appendChild(document.createTextNode(` ${String(actionText ?? '')}`));
    actionBtn.addEventListener('click', () => { actionCallback(); dismissToast(); });
    actionsDiv.appendChild(actionBtn);
    toastElement.appendChild(actionsDiv);
  }

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'toast-close-btn';
  closeBtn.setAttribute('aria-label', 'Dismiss notification');
  closeBtn.textContent = '×';
  closeBtn.addEventListener('click', dismissToast);
  toastElement.appendChild(closeBtn);

  stack.appendChild(toastElement);

  // Action toasts linger longer so there is time to click; errors stay a little longer than successes.
  const lifetime = actionCallback ? (duration ?? 8000) : (duration ?? (isSuccess ? 3800 : 6000));
  dismissTimer = setTimeout(dismissToast, lifetime);
  toastElement.addEventListener('mouseenter', () => clearTimeout(dismissTimer));
  toastElement.addEventListener('mouseleave', () => { dismissTimer = setTimeout(dismissToast, 2000); });
}

export function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => { clearTimeout(timeout); func(...args); };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
};

// silent: suppress toasts. showLoading: the full-screen overlay; by default it is used
// only when no triggering button is given (a button shows its own busy state instead).
export function useApi(apiCall, element = null, silent = false, showLoading = undefined) {
    const loadingOverlay = document.getElementById('loading-overlay');
    let clickedButton = null;

    if (element) {
        clickedButton = element.currentTarget || element;
        if (clickedButton) {
            clickedButton.disabled = true;
            clickedButton.classList.add('is-busy');
            clickedButton.setAttribute('aria-busy', 'true');
        }
    }

    const useOverlay = showLoading ?? !clickedButton;
    if (useOverlay && loadingOverlay) loadingOverlay.classList.remove('hidden');

    return apiCall.then(async (response) => {
        if (response.status === 'ok' && !silent) {
            // Background fetches carry no message and stay quiet; actions report the
            // server's own message, or a short confirmation when it sent none.
            const log = response.data?.log;
            const msg = Array.isArray(log) && log.length ? log.join(' • ') : (clickedButton ? 'Done.' : '');
            const tOpts = response.data?.newItemUrl ? { actionText: 'View on Server', actionCallback: () => window.open(response.data.newItemUrl, '_blank') } : {};
            if (msg) toast(msg, true, tOpts);
        } else if ((response.status === 'error' || response.error?.detail) && !silent) {
            toast('Error: ' + (response.data?.log?.join(' • ') || response.error?.detail || 'Unknown error'), false);
        }
        return response;
    }).catch((err) => {
        if (!silent) toast('Error: ' + (err?.log?.join(' • ') || err?.detail || err.message || 'An unknown error occurred.'), false);
        return { data: null, error: err, status: 'error' };
    }).finally(() => {
        if (useOverlay && loadingOverlay) loadingOverlay.classList.add('hidden');
        if (clickedButton) {
            clickedButton.disabled = false;
            clickedButton.classList.remove('is-busy');
            clickedButton.removeAttribute('aria-busy');
        }
    });
}
