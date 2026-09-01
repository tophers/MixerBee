// static/js/apiClient.js

export const ACCESS_KEY_STORAGE_KEY = 'mixerbeeAccessKey';

export function getStoredAccessKey() {
    return localStorage.getItem(ACCESS_KEY_STORAGE_KEY) || '';
}

export function setStoredAccessKey(key) {
    if (key) localStorage.setItem(ACCESS_KEY_STORAGE_KEY, key);
    else localStorage.removeItem(ACCESS_KEY_STORAGE_KEY);
}

export const api = {
    async request(endpoint, body = null, method = 'GET') {
        const separator = endpoint.includes('?') ? '&' : '?';
        const finalUrl = `${endpoint}${separator}_cb=${Date.now()}`;

        const fetchOptions = {
            method: method.toUpperCase(),
            headers: { 'Content-Type': 'application/json', 'X-MixerBee-Key': getStoredAccessKey() }
        };

        if (!['GET', 'HEAD', 'DELETE'].includes(fetchOptions.method) && body) {
            fetchOptions.body = JSON.stringify(body);
        }

        try {
            const r = await fetch(finalUrl, fetchOptions);

            if (r.status === 401) {
                document.dispatchEvent(new CustomEvent('mixerbee:unauthorized'));
            }

            if (!r.ok) {
                let errData;
                try { errData = await r.json(); } catch(e) { errData = { detail: `Server error: ${r.status}` }; }
                return { data: null, error: errData, status: 'error' };
            }
            
            const res = await r.json();
            return { data: res, error: null, status: res.status || 'ok' };
            
        } catch (err) {
            return { data: null, error: err, status: 'error' };
        }
    },

    get(endpoint) { 
        return this.request(endpoint, null, 'GET'); 
    },
    
    post(endpoint, body) { 
        return this.request(endpoint, body, 'POST'); 
    },
    
    put(endpoint, body) { 
        return this.request(endpoint, body, 'PUT'); 
    },
    
    del(endpoint) { 
        return this.request(endpoint, null, 'DELETE'); 
    }
};
