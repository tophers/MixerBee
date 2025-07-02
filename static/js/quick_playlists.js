// static/js/quick_playlists.js
import { post, smartPlaylistModal, toast } from './utils.js';

export function initQuickPlaylists(userSelectElement, movieGenreData, musicGenreData) {

    document.getElementById('pilot-sampler-btn').addEventListener('click', (event) => {
        const clickedButton = event.currentTarget;
        smartPlaylistModal.show({
            title: 'Pilot Sampler',
            description: 'This will create a playlist with random, unwatched pilot episodes from your library.',
            countLabel: 'Number of Pilots',
            defaultCount: 10,
            defaultName: 'Pilot Sampler',
            onCreate: ({ playlistName, count }) => {
                post('api/create_pilot_sampler', {
                    user_id: userSelectElement.value,
                    playlist_name: playlistName,
                    count: count
                }, clickedButton);
            }
        });
    });

    document.getElementById('continue-watching-btn').addEventListener('click', (event) => {
        const clickedButton = event.currentTarget;
        smartPlaylistModal.show({
            title: 'Continue Watching',
            description: 'This will create a playlist with the next unwatched episode from your most recent in-progress shows.',
            countLabel: 'Number of Shows',
            defaultCount: 10,
            defaultName: 'Continue Watching',
            onCreate: ({ playlistName, count }) => {
                post('api/create_continue_watching_playlist', {
                    user_id: userSelectElement.value,
                    playlist_name: playlistName,
                    count: count
                }, clickedButton);
            }
        });
    });

    document.getElementById('forgotten-favorites-btn').addEventListener('click', (event) => {
        const clickedButton = event.currentTarget;
        smartPlaylistModal.show({
            title: 'From the Vault',
            description: 'This will create a playlist of favorited movies you haven\'t seen in a while.',
            countLabel: 'Number of Movies',
            defaultCount: 20,
            defaultName: 'From the Vault',
            onCreate: ({ playlistName, count }) => {
                post('api/create_forgotten_favorites', {
                    user_id: userSelectElement.value,
                    playlist_name: playlistName,
                    count: count
                }, clickedButton);
            }
        });
    });

    document.getElementById('random-genre-marathon-btn').addEventListener('click', (event) => {
        const clickedButton = event.currentTarget;
        if (!movieGenreData || movieGenreData.length === 0) {
            return toast("Movie genres haven't been loaded yet. Please try again in a moment.", false);
        }
        const randomGenre = movieGenreData[Math.floor(Math.random() * movieGenreData.length)];
        const genreName = randomGenre.Name;
        smartPlaylistModal.show({
            title: `${genreName} Marathon`,
            description: `This will create a playlist of random, unwatched ${genreName} movies from your library.`,
            countLabel: 'Number of Movies',
            defaultCount: 5,
            defaultName: `${genreName} Marathon`,
            onCreate: ({ playlistName, count }) => {
                post('api/create_movie_marathon', {
                    user_id: userSelectElement.value,
                    playlist_name: playlistName,
                    genre: genreName,
                    count: count,
                }, clickedButton);
            }
        });
    });

    document.getElementById('artist-spotlight-btn').addEventListener('click', async (event) => {
        const clickedButton = event.currentTarget;
        const loadingOverlay = document.getElementById('loading-overlay');
        loadingOverlay.style.display = 'flex';
        clickedButton.disabled = true;

        const cleanup = () => {
            loadingOverlay.style.display = 'none';
            clickedButton.disabled = false;
        };

        try {
            const response = await fetch('api/music/random_artist');
            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.detail || 'Could not fetch random artist.');
            }
            const artist = await response.json();
            
            loadingOverlay.style.display = 'none';

            smartPlaylistModal.show({
                title: `Artist Spotlight: ${artist.Name}`,
                description: `This will create a playlist with the most popular tracks from ${artist.Name}.`,
                countLabel: 'Number of Tracks',
                defaultCount: 15,
                defaultName: `Spotlight: ${artist.Name}`,
                onCancel: cleanup,
                onCreate: ({ playlistName, count }) => {
                    post('api/create_artist_spotlight', {
                        user_id: userSelectElement.value,
                        playlist_name: playlistName,
                        artist_id: artist.Id,
                        count: count
                    }, clickedButton);
                }
            });
        } catch (error) {
            toast(`Error: ${error.message}`, false);
            cleanup();
        }
    });

    document.getElementById('album-roulette-btn').addEventListener('click', async (event) => {
        const clickedButton = event.currentTarget;
        const loadingOverlay = document.getElementById('loading-overlay');
        loadingOverlay.style.display = 'flex';
        clickedButton.disabled = true;
    
        const cleanup = () => {
            loadingOverlay.style.display = 'none';
            clickedButton.disabled = false;
        };
    
        try {
            const response = await fetch('api/music/random_album');
            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.detail || 'Could not fetch random album.');
            }
            const album = await response.json();
            const artistName = album.ArtistItems?.[0]?.Name || 'Unknown Artist';
    
            loadingOverlay.style.display = 'none';
    
            smartPlaylistModal.show({
                title: `Album Roulette: ${album.Name}`,
                description: `This will create a playlist of all tracks from "${album.Name}" by ${artistName}.`,
                countInput: false,
                defaultName: album.Name,
                onCancel: cleanup,
                onCreate: ({ playlistName }) => {
                    post('api/create_album_playlist', {
                        user_id: userSelectElement.value,
                        playlist_name: playlistName,
                        album_id: album.Id
                    }, clickedButton);
                }
            });
        } catch (error) {
            toast(`Error: ${error.message}`, false);
            cleanup();
        }
    });

    document.getElementById('music-genre-sampler-btn').addEventListener('click', (event) => {
        const clickedButton = event.currentTarget;
        if (!musicGenreData || musicGenreData.length === 0) {
            return toast("Music genres haven't been loaded yet. Please try again in a moment.", false);
        }
        const randomGenre = musicGenreData[Math.floor(Math.random() * musicGenreData.length)];
        const genreName = randomGenre.Name;
        smartPlaylistModal.show({
            title: `Genre Sampler: ${genreName}`,
            description: `This will create a playlist of random songs from the ${genreName} genre.`,
            countLabel: 'Number of Songs',
            defaultCount: 20,
            defaultName: `Sampler: ${genreName}`,
            onCreate: ({ playlistName, count }) => {
                post('api/create_music_genre_playlist', {
                    user_id: userSelectElement.value,
                    playlist_name: playlistName,
                    genre: genreName,
                    count: count,
                }, clickedButton);
            }
        });
    });
}