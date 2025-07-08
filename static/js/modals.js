// static/js/modals.js
import { toast } from './utils.js';

// MODAL SYSTEM
class BaseModal {
    constructor(modalId, config = {}) {
        this.modalId = modalId;
        this.config = config;
        this.eventHandlers = new Map();
    }

    init() {
        this.overlay = document.getElementById(this.modalId);
        if (!this.overlay) {
            console.error(`Modal overlay with ID "${this.modalId}" not found.`);
            return;
        }
        this.closeBtn = this.overlay.querySelector(this.config.closeBtn);
        this.cancelBtn = this.overlay.querySelector(this.config.cancelBtn);
        this.confirmBtn = this.overlay.querySelector(this.config.confirmBtn);

        // Bind core event handlers once
        this._handleKeyDown = this._onKeyDown.bind(this);
        this._handleClose = this.hide.bind(this);
    }

    _onKeyDown(e) {
        if (e.key === 'Escape') {
            this.hide();
        }
    }

    _attachEventListeners(listeners) {
        listeners.forEach(({ element, event, handler }) => {
            const boundHandler = handler.bind(this);
            element.addEventListener(event, boundHandler);
            this.eventHandlers.set(handler, { element, event, boundHandler });
        });
    }

    _cleanupEventListeners() {
        this.eventHandlers.forEach(({ element, event, boundHandler }) => {
            element.removeEventListener(event, boundHandler);
        });
        this.eventHandlers.clear();
    }

    show() {
        this._cleanupEventListeners(); // Ensure no old listeners are attached
        const commonListeners = [
            { element: this.closeBtn, event: 'click', handler: this._handleClose },
            { element: this.overlay, event: 'keydown', handler: this._onKeyDown },
        ];
        if (this.cancelBtn) {
            commonListeners.push({ element: this.cancelBtn, event: 'click', handler: this._handleClose });
        }
        this._attachEventListeners(commonListeners);
        this.overlay.style.display = 'flex';
    }

    hide() {
        if (this.onCancelCallback) {
            this.onCancelCallback();
            this.onCancelCallback = null;
        }
        if (this.overlay) {
            this.overlay.style.display = 'none';
        }
        this._cleanupEventListeners();
    }
}

class ConfirmationModal extends BaseModal {
    init() {
        super.init();
        this.titleEl = this.overlay.querySelector('#confirm-modal-title');
        this.textEl = this.overlay.querySelector('#confirm-modal-text');
    }

    _onConfirm() {
        if (this.onConfirmCallback) this.onConfirmCallback();
        this.onCancelCallback = null; // Prevent cancel from firing on confirm
        this.hide();
    }
    
    _onCancel() {
        if (this.onCancelCallback) this.onCancelCallback();
        this.hide();
    }

    hide() {
        if (this.overlay) {
            this.overlay.style.display = 'none';
        }
        this._cleanupEventListeners();
    }

    show({ title, text, confirmText = 'Confirm', onConfirm, onCancel }) {
        // Use a slightly different show method that doesn't call super's hide
        this._cleanupEventListeners();
        this.overlay.style.display = 'flex';

        this.onConfirmCallback = onConfirm;
        this.onCancelCallback = onCancel;

        this.titleEl.textContent = title;
        this.textEl.textContent = text;
        this.confirmBtn.textContent = confirmText;
        this.confirmBtn.focus();

        const listeners = [
            { element: this.closeBtn, event: 'click', handler: this._onCancel },
            { element: this.overlay, event: 'keydown', handler: this._onKeyDown },
            { element: this.confirmBtn, event: 'click', handler: this._onConfirm },
        ];
        if (this.cancelBtn) {
            listeners.push({ element: this.cancelBtn, event: 'click', handler: this._onCancel });
        }
        this._attachEventListeners(listeners);
    }
}

class SavePresetModal extends BaseModal {
    init() {
        super.init();
        this.nameInput = this.overlay.querySelector('#preset-name-input');
        this.warning = this.overlay.querySelector('#preset-overwrite-warning');
    }

    _onSave() {
        const presetName = this.nameInput.value.trim();
        if (presetName) {
            if (this.onSaveCallback) this.onSaveCallback(presetName);
            this.hide();
        } else {
            alert('Please enter a name for the preset.');
        }
    }

    _checkOverwrite() {
        this.warning.style.display = this.existingPresets.includes(this.nameInput.value.trim()) ? 'block' : 'none';
    }

    show(onSave, existingPresets = []) {
        super.show();
        this.onSaveCallback = onSave;
        this.onCancelCallback = null;
        this.existingPresets = existingPresets;
        this.nameInput.value = '';
        this.warning.style.display = 'none';
        this.nameInput.focus();

        this._attachEventListeners([
            { element: this.confirmBtn, event: 'click', handler: this._onSave },
            { element: this.nameInput, event: 'input', handler: this._checkOverwrite }
        ]);
    }
}

class SmartPlaylistModal extends BaseModal {
    init() {
        super.init();
        this.titleEl = this.overlay.querySelector('#smart-playlist-title');
        this.descriptionEl = this.overlay.querySelector('#smart-playlist-description');
        this.nameInput = this.overlay.querySelector('#smart-playlist-name-input');
        this.countInput = this.overlay.querySelector('#smart-playlist-count-input');
        this.countLabel = this.overlay.querySelector('#smart-playlist-count-label');
        this.countWrapper = this.overlay.querySelector('#smart-playlist-count-wrapper');
    }

    _onCreate() {
        this.confirmBtn.disabled = true;
        const playlistName = this.nameInput.value.trim();
        const count = this.countWrapper.style.display === 'none' ? 1 : parseInt(this.countInput.value, 10);

        if (playlistName && (this.countWrapper.style.display === 'none' || count > 0)) {
            if (this.onCreateCallback) this.onCreateCallback({ playlistName, count });
            this.onCancelCallback = null; // Prevent cancel from firing on create
            this.hide();
        } else {
            alert('Please provide a valid playlist name and number of items.');
            this.confirmBtn.disabled = false;
        }
    }

    hide() {
        super.hide();
        this.confirmBtn.disabled = false; // Always re-enable on hide
    }

    show({ title, description, countLabel, countInput = true, defaultCount, defaultName, onCreate, onCancel }) {
        super.show();
        this.onCreateCallback = onCreate;
        this.onCancelCallback = onCancel;

        this.titleEl.textContent = title;
        this.descriptionEl.textContent = description;
        this.nameInput.value = defaultName;

        this.countWrapper.style.display = countInput ? '' : 'none';
        if (countInput) {
            this.countLabel.textContent = countLabel;
            this.countInput.value = defaultCount;
        }

        this.nameInput.focus();
        this.nameInput.select();

        this._attachEventListeners([{ element: this.confirmBtn, event: 'click', handler: this._onCreate }]);
    }
}

class ImportPresetModal extends BaseModal {
    init() {
        super.init();
        this.codeInput = this.overlay.querySelector('#import-code-input');
        this.nameInput = this.overlay.querySelector('#import-name-input');
    }

    _onImport() {
        const rawCode = this.codeInput.value.trim();
        const name = this.nameInput.value.trim();
        if (!rawCode || !name) {
            alert('Please provide both a share code and a new name for the preset.');
            return;
        }
        try {
            const lines = rawCode.split('\n').filter(line => line.trim() !== '');
            const base64String = lines.length > 0 ? lines[lines.length - 1] : '';
            if (!base64String) throw new Error("Could not find a valid code in the pasted text.");

            const sharePayload = JSON.parse(atob(base64String));
            if (!sharePayload.data || !Array.isArray(sharePayload.data)) throw new Error("The share code has an invalid format.");

            if (this.onImportCallback) this.onImportCallback(name, sharePayload.data);
            this.hide();
        } catch (e) {
            console.error("Failed to decode or parse preset:", e);
            alert(`Invalid share code. Please check the code and try again.\nError: ${e.message}`);
        }
    }

    show(onImport) {
        super.show();
        this.onImportCallback = onImport;
        this.onCancelCallback = null;
        this.codeInput.value = '';
        this.nameInput.value = '';
        this.codeInput.focus();

        this._attachEventListeners([{ element: this.confirmBtn, event: 'click', handler: this._onImport }]);
    }
}

class SmartBuildModal extends BaseModal {
    init() {
        super.init();
        this.list = this.overlay.querySelector('#smart-build-list');
    }

    _onSelect(event) {
        event.preventDefault();
        const target = event.target.closest('li a');
        if (!target) return;

        const type = target.dataset.type;
        if (this.onSelectCallback) {
            this.onSelectCallback(type);
        }
        this.hide();
    }

    show(items, onSelect) {
        super.show();
        this.onSelectCallback = onSelect;
        this.onCancelCallback = null;
        this.list.innerHTML = ''; // Clear previous items

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

        this._attachEventListeners([{ element: this.list, event: 'click', handler: this._onSelect }]);
    }
}


export let presetModal, smartPlaylistModal, importPresetModal, confirmModal, smartBuildModal;

export function initModals() {
    confirmModal = new ConfirmationModal('confirm-modal-overlay', {
        closeBtn: '#confirm-modal-close-btn',
     //   cancelBtn: '#confirm-modal-cancel-btn',
        confirmBtn: '#confirm-modal-confirm-btn',
    });

    presetModal = new SavePresetModal('save-preset-modal-overlay', {
        closeBtn: '#save-preset-close-btn',
     //   cancelBtn: '#save-preset-cancel-btn',
        confirmBtn: '#save-preset-confirm-btn',
    });

    smartPlaylistModal = new SmartPlaylistModal('smart-playlist-modal-overlay', {
        closeBtn: '#smart-playlist-close-btn',
     //   cancelBtn: '#smart-playlist-cancel-btn',
        confirmBtn: '#smart-playlist-confirm-btn',
    });

    importPresetModal = new ImportPresetModal('import-preset-modal-overlay', {
        closeBtn: '#import-preset-close-btn',
      //  cancelBtn: '#import-preset-cancel-btn',
        confirmBtn: '#import-preset-confirm-btn',
    });

    smartBuildModal = new SmartBuildModal('smart-build-modal-overlay', {
        closeBtn: '#smart-build-close-btn',
     //   cancelBtn: '#smart-build-cancel-btn',
    });

    [confirmModal, presetModal, smartPlaylistModal, importPresetModal, smartBuildModal].forEach(m => m.init());
}