// static/modal.js
import { post } from './utils.js';

export function initModal(userSelectElement) {
    const managePlaylistsBtn = document.getElementById('manage-playlists-btn');
    const modalOverlay = document.getElementById('playlist-modal-overlay');
    const modalCloseBtn = document.getElementById('modal-close-btn');
    const modalPlaylistList = document.getElementById('modal-playlist-list');

    function openPlaylistModal() {
        modalPlaylistList.innerHTML = '<li>Loading playlists...</li>';
        modalOverlay.style.display = 'flex';

        const userId = userSelectElement.value;
        fetch(`api/users/${userId}/playlists`)
            .then(r => r.ok ? r.json() : Promise.reject('Failed to fetch playlists'))
            .then(playlists => {
                modalPlaylistList.innerHTML = '';
                if (playlists.length === 0) {
                    modalPlaylistList.innerHTML = '<li>No playlists found for this user.</li>';
                    return;
                }
                playlists.forEach(p => {
                    const li = document.createElement('li');
                    li.textContent = p.Name;
                    const delBtn = Object.assign(document.createElement('button'), { 
                        className: 'icon-btn danger', 
                        textContent: '🗑️',
                        title: 'Delete Playlist'
                    });

                    delBtn.onclick = (event) => {
                        if (confirm(`Are you sure you want to delete the playlist "${p.Name}"?`)) {
                            post('api/mix', { delete: true, playlist: p.Name, target_uid: userId }, event)
                                .then(status => {
                                    if (status === 'ok') li.remove();
                                });
                        }
                    };
                    li.appendChild(delBtn);
                    modalPlaylistList.appendChild(li);
                });
            })
            .catch(err => { console.error(err); modalPlaylistList.innerHTML = '<li>Error loading playlists.</li>'; });
    }

    function closePlaylistModal() {
        modalOverlay.style.display = 'none';
    }

    managePlaylistsBtn.addEventListener('click', openPlaylistModal);
    modalCloseBtn.addEventListener('click', closePlaylistModal);
    modalOverlay.addEventListener('click', (e) => {
        if (e.target === modalOverlay) closePlaylistModal();
    });
}
