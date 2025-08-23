// static/js/modals.js
import { toast } from './utils.js';

class BaseModal {
    constructor(modalId) {
        this.modalId = modalId;
        this.overlay = document.getElementById(this.modalId);
        if (!this.overlay) {
            console.error(`Modal overlay with ID "${this.modalId}" not found.`);
            return;
        }

        this.closeBtn = this.overlay.querySelector('.js-modal-close');
        this.cancelBtn = this.overlay.querySelector('.js-modal-cancel');

        this._resolvePromise = () => {};
        this._rejectPromise = () => {};

        this._handleKeyDown = this._onKeyDown.bind(this);

        if (this.closeBtn) {
            this.closeBtn.addEventListener('click', () => this.hide(true));
        }
        if (this.cancelBtn) {
            this.cancelBtn.addEventListener('click', () => this.hide(true));
        }
    }

    _onKeyDown(e) {
        if (e.key === 'Escape') {
            this.hide(true);
        }
    }

    show() {
        return new Promise((resolve, reject) => {
            this._resolvePromise = resolve;
            this._rejectPromise = reject;

            this.overlay.classList.remove('hidden');
            document.addEventListener('keydown', this._handleKeyDown);
        });
    }

    hide(isCancel = false) {
        if (this.overlay) {
            this.overlay.classList.add('hidden');
        }
        document.removeEventListener('keydown', this._handleKeyDown);

        if (isCancel) {
            this._rejectPromise(new Error('Modal cancelled by user.'));
        }
    }
}

class ConfirmationModal extends BaseModal {
    constructor(modalId) {
        super(modalId);
        this.titleEl = this.overlay.querySelector('#confirm-modal-title');
        this.textEl = this.overlay.querySelector('#confirm-modal-text');
        this.confirmBtn = this.overlay.querySelector('#confirm-modal-confirm-btn');

        this.confirmBtn.addEventListener('click', () => {
            this.hide(false);
            this._resolvePromise();
        });
    }

    show({ title, text, confirmText = 'Confirm' }) {
        this.titleEl.textContent = title;
        this.textEl.textContent = text;
        this.confirmBtn.textContent = confirmText;
        this.confirmBtn.focus();
        return super.show();
    }
}

class SavePresetModal extends BaseModal {
    constructor(modalId) {
        super(modalId);
        this.nameInput = this.overlay.querySelector('#preset-name-input');
        this.warning = this.overlay.querySelector('#preset-overwrite-warning');
        this.confirmBtn = this.overlay.querySelector('#save-preset-confirm-btn');
        this.existingPresets = [];

        this._checkOverwrite = () => {
            this.warning.style.display = this.existingPresets.includes(this.nameInput.value.trim()) ? 'block' : 'none';
        };

        this.confirmBtn.addEventListener('click', () => {
            const presetName = this.nameInput.value.trim();
            if (presetName) {
                this.hide(false);
                this._resolvePromise(presetName);
            } else {
                toast('Please enter a name for the preset.', false);
            }
        });

        this.nameInput.addEventListener('input', this._checkOverwrite);
    }

    show(existingPresets = []) {
        this.existingPresets = existingPresets;
        this.nameInput.value = '';
        this.warning.style.display = 'none';
        this.nameInput.focus();
        return super.show();
    }
}

class SmartPlaylistModal extends BaseModal {
    constructor(modalId) {
        super(modalId);
        this.titleEl = this.overlay.querySelector('#smart-playlist-title');
        this.descriptionEl = this.overlay.querySelector('#smart-playlist-description');
        this.nameInput = this.overlay.querySelector('#smart-playlist-name-input');
        this.countInput = this.overlay.querySelector('#smart-playlist-count-input');
        this.countLabel = this.overlay.querySelector('#smart-playlist-count-label');
        this.countWrapper = this.overlay.querySelector('#smart-playlist-count-wrapper');
        this.confirmBtn = this.overlay.querySelector('#smart-playlist-confirm-btn');

        this.confirmBtn.addEventListener('click', () => {
            const playlistName = this.nameInput.value.trim();
            const count = this.countWrapper.classList.contains('hidden') ? 1 : parseInt(this.countInput.value, 10);

            if (playlistName && (this.countWrapper.classList.contains('hidden') || count > 0)) {
                this.hide(false);
                this._resolvePromise({ playlistName, count });
            } else {
                toast('Please provide a valid playlist name and number of items.', false);
            }
        });
    }

    hide(isCancel = false) {
        this.confirmBtn.disabled = false;
        super.hide(isCancel);
    }

    show({ title, description, countLabel, countInput = true, defaultCount, defaultName }) {
        this.titleEl.textContent = title;
        this.descriptionEl.textContent = description;
        this.nameInput.value = defaultName;
        this.confirmBtn.disabled = false;

        this.countWrapper.classList.toggle('hidden', !countInput);
        if (countInput) {
            this.countLabel.textContent = countLabel;
            this.countInput.value = defaultCount;
        }

        this.nameInput.focus();
        this.nameInput.select();

        return super.show();
    }
}

class ImportPresetModal extends BaseModal {
    constructor(modalId) {
        super(modalId);
        this.codeInput = this.overlay.querySelector('#import-code-input');
        this.nameInput = this.overlay.querySelector('#import-name-input');
        this.confirmBtn = this.overlay.querySelector('#import-preset-confirm-btn');

        this.confirmBtn.addEventListener('click', () => {
            const rawCode = this.codeInput.value.trim();
            const name = this.nameInput.value.trim();
            if (!rawCode || !name) {
                toast('Please provide both a share code and a new name.', false);
                return;
            }
            try {
                const lines = rawCode.split('\n').filter(line => line.trim() !== '');
                const base64String = lines.length > 0 ? lines[lines.length - 1] : '';
                if (!base64String) throw new Error("Could not find a valid code in the pasted text.");

                const sharePayload = JSON.parse(atob(base64String));
                if (!sharePayload.data || !Array.isArray(sharePayload.data)) {
                    throw new Error("The share code has an invalid format.");
                }

                this.hide(false);
                this._resolvePromise({ name, data: sharePayload.data });
            } catch (e) {
                console.error("Failed to decode or parse preset:", e);
                toast(`Invalid share code. Error: ${e.message}`, false);
            }
        });
    }

    show() {
        this.codeInput.value = '';
        this.nameInput.value = '';
        this.codeInput.focus();
        return super.show();
    }
}

class SmartBuildModal extends BaseModal {
    constructor(modalId) {
        super(modalId);
        this.list = this.overlay.querySelector('#smart-build-list');

        this.list.addEventListener('click', (event) => {
            event.preventDefault();
            const target = event.target.closest('li a');
            if (!target) return;

            const type = target.dataset.type;
            this.hide(false);
            this._resolvePromise(type);
        });
    }

    show(items) {
        this.list.innerHTML = '';
        items.forEach(item => {
            const li = document.createElement('li');
            li.innerHTML = `
                <a href="#" data-type="${item.type}">
                    <div class="item-name"><i data-feather="${item.icon}"></i> ${item.name}</div>
                    <div class="item-description">${item.description}</div>
                </a>
            `;
            this.list.appendChild(li);
        });

        if (window.featherReplace) {
            window.featherReplace();
        }
        return super.show();
    }
}


export let presetModal, smartPlaylistModal, importPresetModal, confirmModal, smartBuildModal;

export function initModals() {
    confirmModal = new ConfirmationModal('confirm-modal-overlay');
    presetModal = new SavePresetModal('save-preset-modal-overlay');
    smartPlaylistModal = new SmartPlaylistModal('smart-playlist-modal-overlay');
    importPresetModal = new ImportPresetModal('import-preset-modal-overlay');
    smartBuildModal = new SmartBuildModal('smart-build-modal-overlay');
}