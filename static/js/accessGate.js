// Login runs before Alpine stores load any account data.
import { setSession } from './apiClient.js';
const overlay = document.getElementById('access-gate-overlay');
const form = document.getElementById('access-gate-form');
const errorEl = document.getElementById('access-gate-error');

export async function ensureUnlocked() {
    const response = await fetch('api/auth/status', { cache: 'no-store' });
    if (!response.ok) throw new Error('Unable to check login status.');
    const state = await response.json();
    if (state.authenticated) {
        setSession(state);
        overlay.hidden = true;
        return;
    }
    overlay.hidden = false;
    const setup = state.setup_required;
    document.getElementById('login-title').textContent = setup ? 'Create your MixerBee owner account' : 'Sign in to MixerBee';
    document.getElementById('setup-instructions').hidden = !setup;
    document.getElementById('password-requirement').hidden = !setup;
    const password = document.getElementById('login-password');
    password.autocomplete = setup ? 'new-password' : 'current-password';
    password.minLength = setup ? 10 : 1;
    form.querySelector('button').textContent = setup ? 'Create account' : 'Sign in';
    errorEl.textContent = '';
    document.getElementById('login-username').focus();
    await new Promise(resolve => {
        form.onsubmit = async event => {
            event.preventDefault();
            const button = form.querySelector('button');
            button.disabled = true;
            errorEl.textContent = '';
            try {
                const r = await fetch(setup ? 'api/auth/setup' : 'api/auth/login', {
                    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-MixerBee-Request': '1' },
                    body: JSON.stringify({ username: document.getElementById('login-username').value,
                        password: password.value })
                });
                const data = await r.json();
                if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Check your login details.');
                password.value = '';
                setSession(data);
                overlay.hidden = true;
                resolve();
            } catch (e) { errorEl.textContent = e.message; }
            finally { button.disabled = false; }
        };
    });
}

// Reload clears all previous account state before another person can log in.
let reloading = false;
document.addEventListener('mixerbee:unauthorized', () => {
    if (reloading) return;
    reloading = true;
    overlay.hidden = false;
    window.location.reload();
});
