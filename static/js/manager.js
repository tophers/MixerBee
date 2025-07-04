// static/js/manager.js
import { post, confirmModal } from './utils.js';

let tableData = [];
let sortColumn = 'Name';
let sortDirection = 'asc';

const managerPane = document.getElementById('manager-pane');
const tableBody = managerPane.querySelector('tbody');
const searchInput = document.getElementById('manager-search-input');
const userSelect = document.getElementById('user-select');

// --- Contents Modal Elements ---
const contentsModalOverlay = document.getElementById('contents-modal-overlay');
const contentsModalTitle = document.getElementById('contents-modal-title');
const contentsModalBody = document.getElementById('contents-modal-body');
const contentsModalCloseBtn = document.getElementById('contents-modal-close-btn');
const contentsModalOkBtn = document.getElementById('contents-modal-ok-btn');

function hideContentsModal() {
    contentsModalOverlay.style.display = 'none';
}

async function showContentsModal(item) {
    contentsModalTitle.textContent = `Contents of "${item.Name}"`;
    contentsModalBody.innerHTML = '<div class="spinner"></div>';
    contentsModalOverlay.style.display = 'flex';

    try {
        const response = await fetch(`api/items/${item.Id}/children?user_id=${userSelect.value}`);
        if (!response.ok) {
            throw new Error('Failed to fetch item contents.');
        }
        const children = await response.json();

        if (children.length === 0) {
            contentsModalBody.innerHTML = '<p style="text-align: center; color: var(--text-subtle);">This item is empty.</p>';
            return;
        }

        const list = document.createElement('ul');
        list.className = 'contents-list';
        children.forEach(child => {
            const li = document.createElement('li');
            li.textContent = child.Name;
            if (child.Type === 'Episode' && child.ParentIndexNumber && child.IndexNumber) {
                li.textContent += ` (S${String(child.ParentIndexNumber).padStart(2, '0')}E${String(child.IndexNumber).padStart(2, '0')})`;
            }
            list.appendChild(li);
        });
        contentsModalBody.innerHTML = '';
        contentsModalBody.appendChild(list);

    } catch (error) {
        console.error(error);
        contentsModalBody.innerHTML = '<p style="color: var(--danger); text-align: center;">Could not load contents.</p>';
    }
}


function sortData() {
    tableData.sort((a, b) => {
        const valA = a[sortColumn];
        const valB = b[sortColumn];

        let comparison = 0;
        if (valA > valB) {
            comparison = 1;
        } else if (valA < valB) {
            comparison = -1;
        }
        return sortDirection === 'asc' ? comparison : comparison * -1;
    });
}

function renderTable() {
    tableBody.innerHTML = '';

    const searchTerm = searchInput.value.toLowerCase();
    // FIX: Defensively handle items that might not have a Name property.
    const filteredData = tableData.filter(item => (item.Name || '').toLowerCase().includes(searchTerm));

    if (filteredData.length === 0) {
        const row = tableBody.insertRow();
        const cell = row.insertCell();
        cell.colSpan = 5;
        cell.textContent = 'No playlists or collections found.';
        cell.style.textAlign = 'center';
        return;
    }

    filteredData.forEach(item => {
        const row = tableBody.insertRow();

        const nameCell = row.insertCell();
        const nameLink = document.createElement('a');
        nameLink.href = '#';
        nameLink.textContent = item.Name;
        nameLink.className = 'item-name-link';
        nameLink.onclick = (e) => {
            e.preventDefault();
            showContentsModal(item);
        };
        nameCell.appendChild(nameLink);

        const typeCell = row.insertCell();
        const typeBadge = document.createElement('span');
        typeBadge.className = `badge ${item.DisplayType.toLowerCase()}`;
        typeBadge.textContent = item.DisplayType;
        typeCell.appendChild(typeBadge);

        row.insertCell().textContent = item.ItemCount;
        row.insertCell().textContent = new Date(item.DateCreated).toLocaleDateString();

        const actionsCell = row.insertCell();
        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'icon-btn danger';
        deleteBtn.innerHTML = '<i data-feather="trash-2"></i>';
        deleteBtn.title = `Delete ${item.DisplayType}`;
        deleteBtn.onclick = (event) => {
            confirmModal.show({
                title: `Delete ${item.DisplayType}?`,
                text: `Are you sure you want to delete the ${item.DisplayType.toLowerCase()} "${item.Name}"? This cannot be undone.`,
                confirmText: 'Delete',
                onConfirm: () => {
                    const userId = userSelect.value;
                    post('api/delete_item', { item_id: item.Id, user_id: userId }, event)
                        .then(res => {
                            if (res.status === 'ok') {
                                row.style.transition = 'opacity 0.4s ease-out';
                                row.style.opacity = '0';
                                setTimeout(() => {
                                    row.remove();
                                    tableData = tableData.filter(d => d.Id !== item.Id);
                                }, 400);
                            }
                        });
                }
            });
        };
        actionsCell.appendChild(deleteBtn);
    });

    if (typeof feather !== 'undefined') {
        feather.replace();
    }
}

function handleSort(event) {
    const newSortColumn = event.target.dataset.sort;
    if (!newSortColumn) return;

    if (sortColumn === newSortColumn) {
        sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
    } else {
        sortColumn = newSortColumn;
        sortDirection = 'asc';
    }

    managerPane.querySelectorAll('th').forEach(th => {
        th.classList.remove('sort-asc', 'sort-desc');
        if (th.dataset.sort === sortColumn) {
            th.classList.add(sortDirection === 'asc' ? 'sort-asc' : 'sort-desc');
        }
    });

    sortData();
    renderTable();
}

export async function initManager() {
    if (!userSelect.value) {
        console.log("Manager: Waiting for user ID...");
        setTimeout(initManager, 200);
        return;
    }

    try {
        const response = await fetch(`api/manageable_items?user_id=${userSelect.value}`);
        if (!response.ok) throw new Error('Failed to fetch manageable items');

        tableData = await response.json();
        sortData(); // Initial sort
        renderTable();

    } catch (err) {
        console.error("Error loading manager data:", err);
        tableBody.innerHTML = '<tr><td colspan="5" style="text-align:center; color: var(--danger);">Error loading data.</td></tr>';
    }
}

searchInput.addEventListener('input', renderTable);
managerPane.querySelector('thead').addEventListener('click', handleSort);
contentsModalCloseBtn.addEventListener('click', hideContentsModal);
contentsModalOkBtn.addEventListener('click', hideContentsModal);