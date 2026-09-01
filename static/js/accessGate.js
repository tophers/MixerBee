// static/js/accessGate.js
//
// Blocks app boot until a valid X-MixerBee-Key is stored in localStorage. The key gates
// nearly every /api/* route (see web.py's enforce_access_key middleware) but deliberately
// NOT /api/webhook, /api/status, or /api/config_status, so this only ever runs against the
// browser UI path, never against Emby/Jellyfin's server-to-server webhook calls.

import { getStoredAccessKey, setStoredAccessKey } from './apiClient.js';

const overlay = document.getElementById('access-gate-overlay');
const form = document.getElementById('access-gate-form');
const input = document.getElementById('access-gate-input');
const errorEl = document.getElementById('access-gate-error');

async function keyIsValid(key) {
    // Deliberately raw fetch, not apiClient.js: this checks an arbitrary candidate key
    // (whatever was just typed), not the one currently in localStorage, so it can't go
    // through api.get()'s automatic getStoredAccessKey() header. It also must not trigger
    // apiClient's mixerbee:unauthorized event for an expected wrong-guess 401 here.
    try {
        const r = await fetch('api/auth/check', { headers: { 'X-MixerBee-Key': key || '' } });
        return r.ok;
    } catch (e) {
        return false;
    }
}

function promptForKey() {
    return new Promise((resolve) => {
        overlay.hidden = false;
        errorEl.textContent = '';
        input.value = '';
        setTimeout(() => input.focus(), 0);

        form.onsubmit = async (e) => {
            e.preventDefault();
            const candidate = input.value.trim();
            if (!candidate) return;

            form.querySelector('button').disabled = true;
            errorEl.textContent = '';

            if (await keyIsValid(candidate)) {
                setStoredAccessKey(candidate);
                overlay.hidden = true;
                resolve();
            } else {
                errorEl.textContent = 'Invalid Access Key.';
                form.querySelector('button').disabled = false;
            }
        };
    });
}

export async function ensureUnlocked() {
    // Always ask the server, even with no stored key: if the admin hasn't opted into the
    // Access Key gate, /api/auth/check succeeds with no header and we skip the prompt entirely.
    const key = getStoredAccessKey();
    if (await keyIsValid(key)) return;

    setStoredAccessKey('');
    await promptForKey();
}

// If a request 401s mid-session (e.g. the key was rotated from another browser), drop the
// stale key and force a full reload once the admin re-enters a valid one.
document.addEventListener('mixerbee:unauthorized', () => {
    if (!overlay.hidden) return;
    setStoredAccessKey('');
    promptForKey().then(() => window.location.reload());
});
