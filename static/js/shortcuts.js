// static/js/shortcuts.js
//
// Global keyboard shortcuts. Single-key shortcuts never fire while typing or while a
// dialog is open; Ctrl/Cmd+Enter is allowed from inside the builder's inputs.

export const SHORTCUTS = [
    { keys: ['1'], label: 'Builder tab' },
    { keys: ['2'], label: 'Assist tab (when AI is on)' },
    { keys: ['3'], label: 'Scheduler tab' },
    { keys: ['4'], label: 'Manager tab' },
    { keys: ['/'], label: 'Focus the AI prompt or Manager search' },
    { keys: ['Ctrl', 'Enter'], label: 'Build the current mix' },
    { keys: ['Ctrl', 'Z'], label: 'Undo block change' },
    { keys: ['Ctrl', 'Shift', 'Z'], label: 'Redo block change' },
    { keys: ['Esc'], label: 'Close dialog or menu' },
    { keys: ['?'], label: 'Show this list' },
];

const TAB_KEYS = { '1': 'mixed', '2': 'assist', '3': 'scheduler', '4': 'manager' };

const isTyping = (el) => !!el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName));
const dialogOpen = () => [...document.querySelectorAll('.modal-overlay, .modal-backdrop')]
    .some(el => el.id !== 'access-gate-overlay' && el.getClientRects().length > 0);
const appReady = () => !!Alpine.store('settings')?.activeUserId;

function focusSearch() {
    const ui = Alpine.store('ui');
    if (ui.currentTab === 'manager') {
        document.getElementById('manager-search-input')?.focus();
        return true;
    }
    if (ui.currentTab === 'mixed' && Alpine.store('settings').generative_ai_available) {
        ui.showAiBuilder = true;
        // The prompt is mounted by x-if, so wait for Alpine to render it.
        Alpine.nextTick(() => document.getElementById('ai-prompt-input')?.focus());
        return true;
    }
    return false;
}

function onKeydown(event) {
    if (event.defaultPrevented || !appReady()) return;
    const mod = event.ctrlKey || event.metaKey;

    if (mod && event.key === 'Enter') {
        const ui = Alpine.store('ui');
        if (ui.currentTab !== 'mixed' || dialogOpen()) return;
        // Leave Ctrl+Enter in the AI prompt to mean "generate".
        if (document.activeElement?.id === 'ai-prompt-input') {
            event.preventDefault();
            Alpine.store('ai').generateWithAi();
            return;
        }
        event.preventDefault();
        Alpine.store('mixer').buildPlaylist(document.getElementById('build-btn'));
        return;
    }

    if (mod || event.altKey || isTyping(document.activeElement) || dialogOpen()) return;

    if (TAB_KEYS[event.key]) {
        event.preventDefault();
        Alpine.store('ui').setTab(TAB_KEYS[event.key]);
    } else if (event.key === '/') {
        if (focusSearch()) event.preventDefault();
    } else if (event.key === '?') {
        event.preventDefault();
        Alpine.store('modals').shortcuts.isOpen = true;
    }
}

export function initShortcuts() {
    document.addEventListener('keydown', onKeydown);
}
