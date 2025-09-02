// static/js/definitions.js

export const SMART_BUILD_TYPES = [
    {
        type: 'recently_added',
        name: 'Recently Added',
        icon: 'zap',
        description: 'The latest movies and episodes added to your library.',
        schedulable: true
    },
    {
        type: 'next_up',
        name: 'Next Up',
        icon: 'play',
        description: 'Next episodes from your in-progress shows.',
        schedulable: true
    },
    {
        type: 'pilot_sampler',
        name: 'Pilot Sampler',
        icon: 'film',
        description: 'Random pilot episodes from un-watched shows.',
        schedulable: true
    },
    {
        type: 'from_the_vault',
        name: 'From the Vault',
        icon: 'archive',
        description: 'Favorite movies you haven\'t watched in a while.',
        schedulable: true
    },
    {
        type: 'genre_roulette',
        name: 'Movie Genre Roulette',
        icon: 'shuffle',
        description: 'A movie marathon from a random genre.',
        schedulable: false
    },
    {
        type: 'artist_spotlight',
        name: 'Artist Spotlight',
        icon: 'star',
        description: 'Popular tracks from a random artist.',
        schedulable: false
    },
    {
        type: 'album_roulette',
        name: 'Album Roulette',
        icon: 'disc',
        description: 'A full playlist from a random album.',
        schedulable: false
    },
    {
        type: 'genre_sampler',
        name: 'Music Genre Sampler',
        icon: 'git-merge',
        description: 'A mix of songs from a random music genre.',
        schedulable: false
    },
];