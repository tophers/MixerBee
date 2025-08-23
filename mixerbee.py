#!/usr/bin/env python3
"""
mixerbee.py – command-line wrapper for mixerbee

Adds new options:

    --user NAME     create / delete the playlist on behalf of “NAME”.
                    (You must authenticate with an Emby admin account.)

    -i, --interactive
                    Run in interactive wizard mode to build the playlist.

Examples
--------
# Build a mix under your own account (default)
./mixerbee "X-Files::S1E1" "Almost Human::S1E1" --count 5

# Run the interactive wizard to be prompted for everything
./mixerbee --interactive
"""
from __future__ import annotations

import argparse
import sys
from typing import Dict, List

import requests

import app as core


def mix(*,
        shows: List[str],
        count: int,
        playlist: str,
        target_uid: str | None = None,
        delete: bool = False,
        verbose: bool = False) -> Dict[str, object]:
    """
    Legacy mix function for the CLI. This is a simplified version
    that only handles TV shows for command-line use.
    """
    log: List[str] = []
    try:
        login_uid, token = core.authenticate(core.EMBY_USER, core.EMBY_PASS)
    except requests.HTTPError as err:
        return {"status": "error",
                "log": [f"Login failed: {err.response.text}"]}

    hdr = core.auth_headers(token, login_uid)
    tgt = target_uid or login_uid

    if verbose:
        log.append(f"Authenticated as {core.EMBY_USER} → uid={login_uid}")
        if target_uid:
            log.append(f"Acting on behalf of user id {tgt}")

    if delete:
        core.delete_collection(playlist, tgt, hdr, log)
        core.delete_playlist(playlist, tgt, hdr, log)
        return {"status": "ok", "log": log,
                "details": {"deleted": playlist, "user_id": tgt}}

    if not shows:
        return {"status": "error",
                "log": ["No shows specified; nothing to do."]}

    groups: List[List[dict]] = []
    for raw in shows:
        try:
            name, s, e = core.parse_show(raw)
        except ValueError as err:
            return {"status": "error", "log": [str(err)]}
        sid = core.series_id(name, hdr)
        if not sid:
            return {"status": "error",
                    "log": [f"Show not found: {name}"]}

        eps = core.episodes(sid, s, e, count, hdr)
        if len(eps) < count:
            log.append(f"Warning: only {len(eps)} eps found for "
                       f"'{name}' starting S{s}E{e}")
        groups.append(eps)

    interleaved_ids = core.interleave(groups)
    total = len(interleaved_ids)

    if verbose:
        log.append(f"Creating playlist with {total} episodes…")

    core.create_playlist(playlist, tgt, interleaved_ids, hdr, log)
    return {"status": "ok", "log": log,
            "details": {"episodes": total,
                        "playlist": playlist,
                        "user_id": tgt}}


def run_interactive_wizard(hdr: dict, initial_uid: str) -> dict:
    """Runs an interactive wizard to gather playlist details from the user."""

    print("\n=== MixerBee Interactive Wizard ===")
    show_args = []

    while True:
        print("-" * 30)
        query = input("Search for a show (or press Enter to finish adding shows): ")
        if not query.strip():
            break

        try:
            results = core.search_series(query, hdr)
            if not results:
                print(f"  -> No matches found for '{query}'. Please try again.")
                continue

            print("  -> Found matches:")
            for i, show in enumerate(results, 1):
                print(f"    {i}. {show['Name']}")

            while True:
                try:
                    choice_str = input("Select a number (or 0 to search again): ")
                    choice = int(choice_str)
                    if 0 <= choice <= len(results):
                        break
                    else:
                        print("  -> Invalid number, please try again.")
                except ValueError:
                    print("  -> Please enter a number.")

            if choice == 0:
                continue

            selected_show = results[choice - 1]
            print(f"  -> Selected: {selected_show['Name']}")

            s = input("  Enter start season [1]: ") or "1"
            e = input("  Enter start episode [1]: ") or "1"

            show_arg_str = f"{selected_show['Name']}::S{s.zfill(2)}E{e.zfill(2)}"
            show_args.append(show_arg_str)
            print(f"  -> Added '{show_arg_str}' to the list.")

        except Exception as e:
            print(f"An error occurred: {e}")

    if not show_args:
        print("\nNo shows were selected. Exiting.")
        return {"status": "cancelled", "log": []}

    print("\n--- Final Playlist Details ---")
    count = input("Episodes per show [5]: ") or "5"
    playlist_name = input("Playlist name [MixerBee Playlist]: ") or "MixerBee Playlist"

    target_uid = initial_uid

    print("\n--- Summary ---")
    print(f"Playlist Name: {playlist_name}")
    print(f"Episodes/Show: {count}")
    print("Shows to Mix:")
    for s in show_args:
        print(f"  - {s}")

    confirm = input("\nBuild this playlist? [y/N]: ").lower()
    if confirm not in ('y', 'yes'):
        print("Cancelled by user. Exiting.")
        return {"status": "cancelled", "log": []}

    print("\nProcessing...")
    return mix(
        shows=show_args,
        count=int(count),
        playlist=playlist_name,
        target_uid=target_uid,
        delete=False,
        verbose=False,
    )


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Create or delete interleaved TV episode playlists in Emby",
    )
    ap.add_argument("shows", nargs="*", help="Each as 'Show::S3E1'")
    ap.add_argument("--count", type=int, default=5, help="Episodes per show")
    ap.add_argument("--playlist", default="MixerBee Playlist",
                    help="Playlist name for create mode")
    ap.add_argument("--delete", metavar="NAME",
                    help="Delete playlist by name and exit")
    ap.add_argument("--user", metavar="NAME",
                    help="Target Emby username (default = current login user)")
    ap.add_argument("--verbose", action="store_true", help="Extra output")
    ap.add_argument("-i", "--interactive", action="store_true",
                    help="Run in interactive wizard mode to build the playlist")
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    try:
        login_uid, token = core.authenticate(core.EMBY_USER, core.EMBY_PASS)
    except Exception as err:
        print(f"Login failed: {err}", file=sys.stderr)
        sys.exit(1)

    hdr = core.auth_headers(token, login_uid)

    if args.interactive:
        result = run_interactive_wizard(hdr, login_uid)
    else:
        if args.user:
            target_uid = core.user_id_by_name(args.user, hdr)
            if not target_uid:
                print(f"User '{args.user}' not found in Emby.", file=sys.stderr)
                sys.exit(1)
        else:
            target_uid = None

        result = mix(
            shows=args.shows,
            count=args.count,
            playlist=args.delete or args.playlist,
            target_uid=target_uid,
            delete=bool(args.delete),
            verbose=args.verbose,
        )

    for line in result.get("log", []):
        print(line)

    if result.get("status") != "ok":
        sys.exit(1)


if __name__ == "__main__":
    main()
