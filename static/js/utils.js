// static/js/utils.js

export const toastHistory = [];

export function toast(message, isSuccess, options = {}) {
  const { actionCallback, actionText = 'View' } = options;

  const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  toastHistory.unshift({ message, isSuccess, timestamp });
  if (toastHistory.length > 50) toastHistory.pop();
  document.dispatchEvent(new CustomEvent('toast-added'));

  document.querySelectorAll('.toast').forEach(t => t.remove());

  const toastElement = document.createElement('div');
  toastElement.className = `toast ${isSuccess ? 'ok' : 'fail'}`;

  let contentHTML = `<div class="toast-message">${message}</div>`;

  if (actionCallback) {
    const icon = typeof Alpine !== 'undefined' ? Alpine.store('icons').externalLink : '';
    contentHTML += `
      <div class="toast-actions">
        <button type="button" class="toast-button align-center gap-xs">
          ${icon} ${actionText}
        </button>
      </div>
    `;
  }

  toastElement.innerHTML = contentHTML;

  if (actionCallback) {
    toastElement.querySelector('.toast-button').addEventListener('click', () => {
      actionCallback();
      toastElement.style.animation = 'fadeOutUp 0.5s forwards';
      toastElement.addEventListener('animationend', () => toastElement.remove());
    });
  }

  const closeBtn = document.createElement('button');
  closeBtn.className = 'toast-close-btn';
  closeBtn.innerHTML = '&times;';
  closeBtn.onclick = () => {
    toastElement.style.animation = 'fadeOutUp 0.5s forwards';
    toastElement.addEventListener('animationend', () => toastElement.remove());
  };
  toastElement.appendChild(closeBtn);

  document.body.appendChild(toastElement);

  if (!actionCallback) {
    toastElement.style.animation = 'fadeInDown 0.5s, fadeOutUp 0.5s 3.2s forwards';
    setTimeout(() => {
        if (toastElement.parentNode) {
            toastElement.remove();
        }
    }, 4300);
  } else {
    toastElement.style.animation = 'fadeInDown 0.5s forwards';
  }
}

export function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
};

export function post(endpoint, body, eventOrElement = null, method = 'POST', silent = false, showLoading = true) {
  const loadingOverlay = document.getElementById('loading-overlay');
  let clickedButton = null;

  if (eventOrElement) {
    if (eventOrElement.currentTarget) {
        clickedButton = eventOrElement.currentTarget;
    } else if (eventOrElement.tagName) {
        clickedButton = eventOrElement;
    }

    if (clickedButton) {
        clickedButton.disabled = true;
    }
  }

  if (showLoading && loadingOverlay) loadingOverlay.classList.remove('hidden');

  return fetch(endpoint, {
    method: method,
    headers: { 'Content-Type': 'application/json' },
    body: (method.toUpperCase() !== 'DELETE') ? JSON.stringify(body) : undefined
  })
    .then(r => {
        if (!r.ok) {
            return r.json().catch(() => {
                return { status: 'error', detail: `Server error: ${r.status} ${r.statusText}` };
            }).then(err => Promise.reject(err));
        }
        return r.json();
    })
    .then(res => {
        if (res.status === 'ok') {
            if (!silent) {
                const successMessage = res.log?.join(' • ') || 'Success!';
                const toastOptions = {};
                if (res.newItemUrl) {
                    toastOptions.actionText = 'View on Server';
                    toastOptions.actionCallback = () => window.open(res.newItemUrl, '_blank');
                }
                toast(successMessage, true, toastOptions);
            }
        }
        else if (res.status === 'error' || res.detail) {
            const errorMessage = res.log?.join(' • ') || res.detail || 'Unknown error';
            toast('Error: ' + errorMessage, false);
        }
        return res;
    })
    .catch(err => {
        const errorMessage = err.log?.join(' • ') || err.detail || err.message || 'An unknown error occurred.';
        toast('Error: ' + errorMessage, false);
        return { status: 'error', detail: errorMessage };
    })
    .finally(() => {
        if (showLoading && loadingOverlay) loadingOverlay.classList.add('hidden');
        if (clickedButton) clickedButton.disabled = false;
    });
}
