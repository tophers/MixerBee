// static/js/quick_playlists.js
import { post, smartPlaylistModal, toast } from './utils.js';

let clickEventCounter = 0;

export function initQuickPlaylists(userSelectElement, movieGenreData, musicGenreData) {

    document.getElementById('pilot-sampler-btn').addEventListener('click', (event) => {
        const eventId = ++clickEventCounter;
        console.log(`[Event ${eventId}] 'Pilot Sampler' button clicked at ${new Date().toISOString()}. Disabling button.`);
        const clickedButton = event.currentTarget;
        clickedButton.disabled = true;

        smartPlaylistModal.show({
            title: 'Pilot Sampler',
            description: 'This will create a playlist with random, unwatched pilot episodes from your library.',
            countLabel: 'Number of Pilots',
            defaultCount: 10,
            defaultName: 'Pilot Sampler',
            onCancel: () => {
                console.log(`[Event ${eventId}] Modal cancelled. Re-enabling button.`);
                clickedButton.disabled = false;
            },
            onCreate: ({ playlistName, count }) => {
                console.log(`[Event ${eventId}] Modal 'Create' clicked. Calling post().`);
                post('api/create_pilot_sampler', {
                    user_id: userSelectElement.value,
                    playlist_name: playlistName,
                    count: count
                }, clickedButton).finally(() => {
                    console.log(`[Event ${eventId}] post() has completed.`);
                });
            }
        });
    });

    document.getElementById('continue-watching-btn').addEventListener('click', (event) => {
        const eventId = ++clickEventCounter;
        console.log(`[Event ${eventId}] 'Next Up' button clicked at ${new Date().toISOString()}. Disabling button.`);
        const clickedButton = event.currentTarget;
        clickedButton.disabled = true;

        smartPlaylistModal.show({
            title: 'Continue Watching',
            description: 'This will create a playlist with the next unwatched episode from your most recent in-progress shows.',
            countLabel: 'Number of Shows',
            defaultCount: 10,
            defaultName: 'Continue Watching',
            onCancel: () => {
                console.log(`[Event ${eventId}] Modal cancelled. Re-enabling button.`);
                clickedButton.disabled = false;
            },
            onCreate: ({ playlistName, count }) => {
                console.log(`[Event ${eventId}] Modal 'Create' clicked. Calling post().`);
                post('api/create_continue_watching_playlist', {
                    user_id: userSelectElement.value,
                    playlist_name: playlistName,
                    count: count
                }, clickedButton).finally(() => {
                    console.log(`[Event ${eventId}] post() has completed.`);
                });
            }
        });
    });

    document.getElementById('forgotten-favorites-btn').addEventListener('click', (event) => {
        const eventId = ++clickEventCounter;
        console.log(`[Event ${eventId}] 'From the Vault' button clicked at ${new Date().toISOString()}. Disabling button.`);
        const clickedButton = event.currentTarget;
        clickedButton.disabled = true;

        smartPlaylistModal.show({
            title: 'From the Vault',
            description: 'This will create a playlist of favorited movies you haven\'t seen in a while.',
            countLabel: 'Number of Movies',
            defaultCount: 20,
            defaultName: 'From the Vault',
            onCancel: () => {
                console.log(`[Event ${eventId}] Modal cancelled. Re-enabling button.`);
                clickedButton.disabled = false;
            },
            onCreate: ({ playlistName, count }) => {
                console.log(`[Event ${eventId}] Modal 'Create' clicked. Calling post().`);
                post('api/create_forgotten_favorites', {
                    user_id: userSelectElement.value,
                    playlist_name: playlistName,
                    count: count
                }, clickedButton).finally(() => {
                    console.log(`[Event ${eventId}] post() has completed.`);
                });
            }
        });
    });

    document.getElementById('random-genre-marathon-btn').addEventListener('click', (event) => {
        const eventId = ++clickEventCounter;
        console.log(`[Event ${eventId}] 'Genre Roulette' button clicked at ${new Date().toISOString()}. Disabling button.`);
        const clickedButton = event.currentTarget;
        clickedButton.disabled = true;

        if (!movieGenreData || movieGenreData.length === 0) {
            clickedButton.disabled = false;
            return toast("Movie genres haven't been loaded yet. Please try again in a moment.", false);
        }
        const randomGenre = movieGenreData[Math.floor(Math.random() * movieGenreData.length)];
        const genreName = randomGenre.Name;
        smartPlaylistModal.show({
            title: `MixerBee Roulette: ${genreName}`,
            description: `This will create a playlist of random, unwatched ${genreName} movies from your library.`,
            countLabel: 'Number of Movies',
            defaultCount: 5,
            defaultName: `MixerBee Roulette: ${genreName}`,
            onCancel: () => {
                console.log(`[Event ${eventId}] Modal cancelled. Re-enabling button.`);
                clickedButton.disabled = false;
            },
            onCreate: ({ playlistName, count }) => {
                console.log(`[Event ${eventId}] Modal 'Create' clicked. Calling post().`);
                post('api/create_movie_marathon', {
                    user_id: userSelectElement.value,
                    playlist_name: playlistName,
                    genre: genreName,
                    count: count,
                }, clickedButton).finally(() => {
                    console.log(`[Event ${eventId}] post() has completed.`);
                });
            }
        });
    });

    document.getElementById('artist-spotlight-btn').addEventListener('click', async (event) => {
        const eventId = ++clickEventCounter;
        console.log(`[Event ${eventId}] 'Artist Spotlight' button clicked at ${new Date().toISOString()}. Disabling button.`);
        const clickedButton = event.currentTarget;
        const loadingOverlay = document.getElementById('loading-overlay');
        loadingOverlay.style.display = 'flex';
        clickedButton.disabled = true;

        const cleanup = () => {
            loadingOverlay.style.display = 'none';
            console.log(`[Event ${eventId}] 'Artist Spotlight' cleanup. Re-enabling button.`);
            clickedButton.disabled = false;
        };

        try {
            const response = await fetch('api/music/random_artist');
            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.detail || 'Could not fetch random artist.');
            }
            const artist = await response.json();

            loadingOverlay.style.display = 'none'; // Hide loading before showing modal

            smartPlaylistModal.show({
                title: `MixerBee Spotlight: ${artist.Name}`,
                description: `This will create a playlist with the most popular tracks from ${artist.Name}.`,
                countLabel: 'Number of Tracks',
                defaultCount: 15,
                defaultName: `MixerBee Spotlight: ${artist.Name}`,
                onCancel: cleanup,
                onCreate: ({ playlistName, count }) => {
                    console.log(`[Event ${eventId}] Modal 'Create' clicked. Calling post().`);
                    post('api/create_artist_spotlight', {
                        user_id: userSelectElement.value,
                        playlist_name: playlistName,
                        artist_id: artist.Id,
                        count: count
                    }, clickedButton).finally(() => {
                        console.log(`[Event ${eventId}] post() has completed.`);
                        cleanup();
                    });
                }
            });
        } catch (error) {
            toast(`Error: ${error.message}`, false);
            cleanup();
        }
    });

    document.getElementById('album-roulette-btn').addEventListener('click', async (event) => {
        const eventId = ++clickEventCounter;
        console.log(`[Event ${eventId}] 'Album Roulette' button clicked at ${new Date().toISOString()}. Disabling button.`);
        const clickedButton = event.currentTarget;
        const loadingOverlay = document.getElementById('loading-overlay');
        loadingOverlay.style.display = 'flex';
        clickedButton.disabled = true;

        const cleanup = () => {
            loadingOverlay.style.display = 'none';
            console.log(`[Event ${eventId}] 'Album Roulette' cleanup. Re-enabling button.`);
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
                title: `MixerBee Album: ${album.Name}`,
                description: `This will create a playlist of all tracks from "${album.Name}" by ${artistName}.`,
                countInput: false,
                defaultName: `MixerBee Album: ${album.Name}`,
                onCancel: cleanup,
                onCreate: ({ playlistName }) => {
                    console.log(`[Event ${eventId}] Modal 'Create' clicked. Calling post().`);
                    post('api/create_album_playlist', {
                        user_id: userSelectElement.value,
                        playlist_name: playlistName,
                        album_id: album.Id
                    }, clickedButton).finally(() => {
                        console.log(`[Event ${eventId}] post() has completed.`);
                        cleanup();
                    });
                }
            });
        } catch (error) {
            toast(`Error: ${error.message}`, false);
            cleanup();
        }
    });

    document.getElementById('music-genre-sampler-btn').addEventListener('click', (event) => {
        const eventId = ++clickEventCounter;
        console.log(`[Event ${eventId}] 'Music Genre Sampler' button clicked at ${new Date().toISOString()}. Disabling button.`);
        const clickedButton = event.currentTarget;
        clickedButton.disabled = true;

        if (!musicGenreData || musicGenreData.length === 0) {
            clickedButton.disabled = false;
            return toast("Music genres haven't been loaded yet. Please try again in a moment.", false);
        }
        const randomGenre = musicGenreData[Math.floor(Math.random() * musicGenreData.length)];
        const genreName = randomGenre.Name;
        smartPlaylistModal.show({
            title: `MixerBee Sampler: ${genreName}`,
            description: `This will create a playlist of random songs from the ${genreName} genre.`,
            countLabel: 'Number of Songs',
            defaultCount: 20,
            defaultName: `MixerBee Sampler: ${genreName}`,
            onCancel: () => {
                console.log(`[Event ${eventId}] Modal cancelled. Re-enabling button.`);
                clickedButton.disabled = false;
            },
            onCreate: ({ playlistName, count }) => {
                console.log(`[Event ${eventId}] Modal 'Create' clicked. Calling post().`);
                post('api/create_music_genre_playlist', {
                    user_id: userSelectElement.value,
                    playlist_name: playlistName,
                    genre: genreName,
                    count: count,
                }, clickedButton).finally(() => {
                    console.log(`[Event ${eventId}] post() has completed.`);
                });
            }
        });
    });
}