// static/js/utils.js
export function toast(m, ok) {
  const t = Object.assign(document.createElement('div'), { className: 'toast ' + (ok ? 'ok' : 'fail'), textContent: m });
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2500);
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
            toast(successMessage, true);
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
