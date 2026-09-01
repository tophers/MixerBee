// static/js/utils.js

export const toastHistory = [];

export function generateUUID() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return ([1e7] + -1e3 + -4e3 + -8e3 + -1e11).replace(/[018]/g, c =>
    (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16)
  );
}

export function toast(message, isSuccess, options = {}) {
  const { actionCallback, actionText = 'View' } = options;

  const timestamp = new Date().toLocaleTimeString([], {
    hour: '2-digit', minute: '2-digit', second: '2-digit'
  });

  toastHistory.unshift({ message, isSuccess, timestamp });
  if (toastHistory.length > 50) toastHistory.pop();

  document.dispatchEvent(new CustomEvent('toast-added'));
  document.querySelectorAll('.toast').forEach(t => t.remove());

  const toastElement = document.createElement('div');
  toastElement.className = `toast ${isSuccess ? 'ok' : 'fail'}`;

  const dismissToast = () => {
    toastElement.style.animation = 'fadeOutUp 0.5s forwards';
    toastElement.addEventListener('animationend', () => toastElement.remove(), { once: true });
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

    const icon = typeof Alpine !== 'undefined' ? Alpine.store('icons')?.externalLink : '';
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
  closeBtn.textContent = '×';
  closeBtn.addEventListener('click', dismissToast);
  toastElement.appendChild(closeBtn);
  
  document.body.appendChild(toastElement);

  if (!actionCallback) {
    toastElement.style.animation = 'fadeInDown 0.5s, fadeOutUp 0.5s 3.2s forwards';
    setTimeout(() => { if (toastElement.parentNode) toastElement.remove(); }, 4300);
  } else {
    toastElement.style.animation = 'fadeInDown 0.5s forwards';
  }
}

export function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => { clearTimeout(timeout); func(...args); };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
};

export function useApi(apiCall, element = null, silent = false, showLoading = true) {
    const loadingOverlay = document.getElementById('loading-overlay');
    let clickedButton = null;

    if (element) {
        clickedButton = element.currentTarget || element;
        if (clickedButton) clickedButton.disabled = true;
    }

    if (showLoading && loadingOverlay) loadingOverlay.classList.remove('hidden');

    return apiCall.then(async (response) => {
        if (response.status === 'ok' && !silent) {
            const msg = response.data?.log?.join(' • ') || 'All good!';
            const tOpts = response.data?.newItemUrl ? { actionText: 'View on Server', actionCallback: () => window.open(response.data.newItemUrl, '_blank') } : {};
            toast(msg, true, tOpts);
        } else if ((response.status === 'error' || response.error?.detail) && !silent) {
            toast('Error: ' + (response.data?.log?.join(' • ') || response.error?.detail || 'Unknown error'), false);
        }
        return response;
    }).catch((err) => {
        if (!silent) toast('Error: ' + (err?.log?.join(' • ') || err?.detail || err.message || 'An unknown error occurred.'), false);
        return { data: null, error: err, status: 'error' };
    }).finally(() => {
        if (showLoading && loadingOverlay) loadingOverlay.classList.add('hidden');
        if (clickedButton) clickedButton.disabled = false;
    });
}
