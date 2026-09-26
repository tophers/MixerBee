// static/js/apiClient.js

let session = {};
export function setSession(value) { session = value; }
export function getSession() { return session; }

export const api = {
    async request(endpoint, body = null, method = 'GET') {
        const separator = endpoint.includes('?') ? '&' : '?';
        const finalUrl = `${endpoint}${separator}_cb=${Date.now()}`;

        const fetchOptions = {
            method: method.toUpperCase(),
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-MixerBee-Request': '1',
                'X-MixerBee-CSRF': session.csrf_token || '',
                'X-MixerBee-Account': session.account?.id || '',
                'X-MixerBee-Connection': session.connection_id || '' }
        };

        if (!['GET', 'HEAD', 'DELETE'].includes(fetchOptions.method) && body) {
            fetchOptions.body = JSON.stringify(body);
        }

        try {
            const r = await fetch(finalUrl, fetchOptions);

            if (r.status === 401 || r.status === 409) {
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
