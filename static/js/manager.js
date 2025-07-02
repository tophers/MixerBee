// static/manager.js
import { post } from './utils.js';

let tableData = [];
let sortColumn = 'Name';
let sortDirection = 'asc';

const managerPane = document.getElementById('manager-pane');
const tableBody = managerPane.querySelector('tbody');
const searchInput = document.getElementById('manager-search-input');

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
    const filteredData = tableData.filter(item => item.Name.toLowerCase().includes(searchTerm));

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

        row.insertCell().textContent = item.Name;

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
             if (confirm(`Are you sure you want to delete the ${item.DisplayType.toLowerCase()} "${item.Name}"?`)) {
                post('api/delete_item', { item_id: item.Id }, event)
                    .then(status => {
                        if (status === 'ok') {
                           // Animate-out and remove the row for a better UX
                           row.style.transition = 'opacity 0.4s ease-out';
                           row.style.opacity = '0';
                           setTimeout(() => {
                               row.remove();
                               // Also remove from the underlying data model to keep it consistent
                               // if the user sorts or filters again without a full refresh.
                               tableData = tableData.filter(d => d.Id !== item.Id);
                           }, 400);
                        }
                    });
            }
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

    // Update header indicators
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
    const userSelect = document.getElementById('user-select');
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