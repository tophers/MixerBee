// static/js/apiClient.js

let session = {};
export function setSession(value) { session = value; }
export function getSession() { return session; }

export const api = {
    async request(endpoint, body = null, method = 'GET') {
        const reqAccount = session.account?.id;
        const reqConnection = session.connection_id;

        let finalUrl = endpoint;
        if (!finalUrl.includes('_cb=')) {
            const separator = finalUrl.includes('?') ? '&' : '?';
            finalUrl = `${finalUrl}${separator}_cb=${Date.now()}`;
        }

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

            let errData = null;
            if (!r.ok) {
                try { errData = await r.json(); } catch(e) { errData = { detail: `Server error: ${r.status}` }; }
                // Some endpoints return a structured detail ({detail, reason}) so callers
                // can tell an AI opt-out from missing setup. Flatten it: every existing
                // consumer concatenates error.detail into a string, and an object there
                // renders as "[object Object]".
                const structured = errData?.detail;
                if (structured && typeof structured === 'object' && !Array.isArray(structured)) {
                    errData = { ...errData, ...structured,
                                detail: String(structured.detail ?? `Server error: ${r.status}`) };
                }
            }

            // 401/409 normally mean the session or account changed, which reloads the
            // page. A 409 that carries a machine-readable reason is a policy answer for
            // one request, not a stale session -- reloading on it would throw away the
            // user's Builder draft every time an unconfigured AI control is touched.
            if ((r.status === 401 || r.status === 409) && !errData?.reason) {
                document.dispatchEvent(new CustomEvent('mixerbee:unauthorized'));
            }

            if (session.account?.id !== reqAccount || session.connection_id !== reqConnection) {
                return { data: null, error: { detail: 'Request context expired or switched' }, status: 'stale' };
            }

            if (!r.ok) {
                if (errData.reason) {
                    // The server is authoritative: a policy rejection means this tab's
                    // capability state is stale, so ask for the current one.
                    document.dispatchEvent(new CustomEvent('mixerbee:policy-rejected',
                        { detail: { reason: errData.reason, status: r.status } }));
                }
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
