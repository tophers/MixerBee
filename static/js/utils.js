// static/js/utils.js

export function toast(message, isSuccess, options = {}) {
  const { actionUrl, actionText = 'View' } = options;
  
  document.querySelectorAll('.toast').forEach(t => t.remove());

  const toastElement = document.createElement('div');
  toastElement.className = `toast ${isSuccess ? 'ok' : 'fail'}`;

  let contentHTML = `<div class="toast-message">${message}</div>`;

  if (actionUrl) {
    contentHTML += `
      <div class="toast-actions">
        <a href="${actionUrl}" target="_blank" class="toast-button">
          <i data-feather="external-link"></i> ${actionText}
        </a>
      </div>
    `;
  }
  
  toastElement.innerHTML = contentHTML;

  const closeBtn = document.createElement('button');
  closeBtn.className = 'toast-close-btn';
  closeBtn.innerHTML = '&times;';
  closeBtn.onclick = () => {
    toastElement.style.animation = 'fadeOutUp 0.5s forwards';
    toastElement.addEventListener('animationend', () => toastElement.remove());
  };
  toastElement.appendChild(closeBtn);

  document.body.appendChild(toastElement);
  
  if (window.featherReplace) {
    window.featherReplace();
  }

  if (!actionUrl) {
    toastElement.style.animation = 'fadeInDown 0.5s, fadeOutUp 0.5s 4.5s forwards';
    setTimeout(() => {
        if (toastElement.parentNode) {
            toastElement.remove();
        }
    }, 5000);
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

export function post(endpoint, body, eventOrElement = null, method = 'POST') {
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

  if (loadingOverlay) loadingOverlay.style.display = 'flex';

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
            const successMessage = res.log?.join(' • ') || 'Success!';
            const toastOptions = {};
            if (res.newItemUrl) {
                toastOptions.actionUrl = res.newItemUrl;
                toastOptions.actionText = 'View on Server';
            }
            toast(successMessage, true, toastOptions);
        } else {
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
        if (loadingOverlay) loadingOverlay.style.display = 'none';
        if (clickedButton) clickedButton.disabled = false;
    });
}
