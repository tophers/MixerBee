// static/js/apiClient.js

import { toast } from './utils.js';

export const api = {
    async request(endpoint, body = null, method = 'GET', element = null, silent = false, showLoading = true) {
        const loadingOverlay = document.getElementById('loading-overlay');
        let clickedButton = null;

        if (element) {
            clickedButton = element.currentTarget || element;
            if (clickedButton) clickedButton.disabled = true;
        }

        if (showLoading && loadingOverlay) loadingOverlay.classList.remove('hidden');

        const separator = endpoint.includes('?') ? '&' : '?';
        const finalUrl = `${endpoint}${separator}_cb=${Date.now()}`;

        const fetchOptions = {
            method: method.toUpperCase(),
            headers: { 'Content-Type': 'application/json' }
        };

        if (!['GET', 'HEAD', 'DELETE'].includes(fetchOptions.method) && body) {
            fetchOptions.body = JSON.stringify(body);
        }

        try {
            const r = await fetch(finalUrl, fetchOptions);
            
            if (!r.ok) {
                let errData;
                try { errData = await r.json(); } catch(e) { errData = { detail: `Server error: ${r.status}` }; }
                throw errData;
            }
            
            const res = await r.json();
            
            if (res.status === 'ok') {
                if (!silent) {
                    const msg = res.log?.join(' • ') || 'Success!';
                    const tOpts = res.newItemUrl ? { actionText: 'View on Server', actionCallback: () => window.open(res.newItemUrl, '_blank') } : {};
                    toast(msg, true, tOpts);
                }
            } else if (res.status === 'error' || res.detail) {
                if (!silent) toast('Error: ' + (res.log?.join(' • ') || res.detail || 'Unknown error'), false);
            }
            return res;
            
        } catch (err) {
            const msg = err.log?.join(' • ') || err.detail || err.message || 'An unknown error occurred.';
            if (!silent) toast('Error: ' + msg, false);
            return { status: 'error', detail: msg };
        } finally {
            if (showLoading && loadingOverlay) loadingOverlay.classList.add('hidden');
            if (clickedButton) clickedButton.disabled = false;
        }
    },

    get(endpoint, silent = false, showLoading = true) { 
        return this.request(endpoint, null, 'GET', null, silent, showLoading); 
    },
    
    post(endpoint, body, element = null, silent = false, showLoading = true) { 
        return this.request(endpoint, body, 'POST', element, silent, showLoading); 
    },
    
    put(endpoint, body, element = null, silent = false, showLoading = true) { 
        return this.request(endpoint, body, 'PUT', element, silent, showLoading); 
    },
    
    del(endpoint, element = null, silent = false, showLoading = true) { 
        return this.request(endpoint, null, 'DELETE', element, silent, showLoading); 
    }
};