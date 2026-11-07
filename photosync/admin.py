"""Local administration; credentials are never exposed through the API."""
import argparse
import secrets
import uuid
from .config import Settings
from .db import connect, initialize, token_digest


def main():
    parser = argparse.ArgumentParser(description="Manage PhotoSync devices")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add-device")
    add.add_argument("name")
    revoke = commands.add_parser("revoke-device")
    revoke.add_argument("id")
    commands.add_parser("list-devices")
    args = parser.parse_args()
    path = Settings.from_env().database
    initialize(path)
    with connect(path) as db:
        if args.command == "add-device":
            device_id, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
            db.execute("INSERT INTO devices(id,name,token_hash) VALUES (?,?,?)", (device_id, args.name, token_digest(token)))
            print(f"Device ID: {device_id}\nToken (shown once): {token}")
        elif args.command == "revoke-device":
            if not db.execute("UPDATE devices SET revoked=1 WHERE id=?", (args.id,)).rowcount:
                parser.error("Unknown device ID")
        else:
            for row in db.execute("SELECT id,name,revoked FROM devices ORDER BY name"):
                print(f"{row['id']}  {row['name']}  {'revoked' if row['revoked'] else 'active'}")


if __name__ == "__main__":
    main()
