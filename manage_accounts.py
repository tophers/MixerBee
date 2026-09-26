"""Small local recovery utility for MixerBee accounts."""
import argparse
import getpass

import accounts
import database


def list_accounts():
    with database.get_db_connection() as conn:
        rows = conn.execute('SELECT username, is_admin FROM accounts ORDER BY username_key').fetchall()
    if not rows:
        print('No local MixerBee accounts exist yet.')
        return
    for row in rows:
        role = 'owner' if row['is_admin'] else 'member'
        print(f"{row['username']}\t{role}")


def reset_password(username):
    with database.get_db_connection() as conn:
        row = conn.execute('SELECT id, username FROM accounts WHERE username_key=?',
                           (username.strip().casefold(),)).fetchone()
    if not row:
        raise ValueError(f"No local MixerBee account named {username!r}.")

    password = getpass.getpass(f"New password for {row['username']}: ")
    confirmation = getpass.getpass('Repeat new password: ')
    if password != confirmation:
        raise ValueError('Passwords do not match.')
    accounts.change_password(row['id'], password)
    print(f"Password changed for {row['username']}. All browser sessions were signed out.")


def main():
    parser = argparse.ArgumentParser(description='Manage local MixerBee accounts from the host.')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list', help='List local accounts and roles.')
    reset = commands.add_parser('reset-password', help='Reset a local account password.')
    reset.add_argument('username')
    args = parser.parse_args()

    database.init_db()
    try:
        if args.command == 'list':
            list_accounts()
        else:
            reset_password(args.username)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
