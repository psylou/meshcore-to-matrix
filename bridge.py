import asyncio
import os
from meshcore import MeshCore, EventType
from nio import (
    AsyncClient, LoginResponse,
    RoomResolveAliasResponse, RoomMessageText,
)

# === CONFIG ===
MATRIX_HOMESERVER = os.environ.get("MATRIX_HOMESERVER")
MATRIX_BOT_USER   = os.environ["MATRIX_BOT_USER"]
MATRIX_PASSWORD   = os.environ["MATRIX_PASSWORD"]
MATRIX_ROOM_ALIAS = os.environ.get("MATRIX_ROOM")

MESH_HOST = os.environ.get("MESH_HOST"")
MESH_PORT = int(os.environ.get("MESH_PORT"))

# Kanal per NAME (ohne führendes #), Index wird automatisch ermittelt
MESH_CHANNEL_NAME = os.environ.get("MESH_CHANNEL_NAME")
MAX_CHANNELS = 16
# ==============


async def find_channel_idx(mc, name: str):
    """Sucht den Kanal-Index anhand des Namens. Gibt None zurück, wenn nicht gefunden."""
    target = name.lstrip("#").strip().lower()
    for idx in range(MAX_CHANNELS):
        res = await mc.commands.get_channel(idx)
        info = res.payload if hasattr(res, "payload") else res
        if not info:
            continue
        ch_name = ""
        if isinstance(info, dict):
            ch_name = (info.get("channel_name")
                       or info.get("name")
                       or "")
        ch_name = str(ch_name).lstrip("#").strip().lower()
        if ch_name == target:
            print(f"✅ Kanal '{name}' gefunden bei Index {idx}")
            return idx
    return None


async def main():
    matrix = AsyncClient(MATRIX_HOMESERVER, MATRIX_BOT_USER)
    mc = None
    try:
        # --- Matrix Login ---
        resp = await matrix.login(MATRIX_PASSWORD)
        if not isinstance(resp, LoginResponse):
            print(f"❌ Matrix-Login fehlgeschlagen: {resp}")
            return
        print(f"✅ Matrix: eingeloggt als {matrix.user_id}")

        r = await matrix.room_resolve_alias(MATRIX_ROOM_ALIAS)
        if not isinstance(r, RoomResolveAliasResponse):
            print(f"❌ Alias nicht auflösbar: {r}")
            return
        room_id = r.room_id
        await matrix.join(room_id)
        print(f"✅ Matrix-Raum: {room_id}")

        # --- MeshCore TCP ---
        mc = await MeshCore.create_tcp(MESH_HOST, MESH_PORT)
        print("✅ MeshCore verbunden")

        # --- Kanal-Index by Name ---
        channel_idx = await find_channel_idx(mc, MESH_CHANNEL_NAME)
        if channel_idx is None:
            print(f"❌ Kanal '{MESH_CHANNEL_NAME}' nicht gefunden. "
                  f"Ist der Companion dem Kanal beigetreten?")
            return

        # === RICHTUNG 1: MeshCore -> Matrix ===
        async def on_channel_msg(event):
            p = event.payload
            ch = p.get("channel_idx", p.get("channel"))
            if ch != channel_idx:
                return  # nur den Ziel-Kanal bridgen
            text = p.get("text", "")
            print(f"[Mesh -> Matrix] ({ch}): {text}")
            await matrix.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": f"[Meshcore] {text}"},
            )

        mc.subscribe(EventType.CHANNEL_MSG_RECV, on_channel_msg)
        await mc.start_auto_message_fetching()
        print("✅ MeshCore Auto-Fetch aktiv")

        # === RICHTUNG 2: Matrix -> MeshCore ===
        async def matrix_listener():
            sync_resp = await matrix.sync(timeout=3000)
            next_batch = sync_resp.next_batch
            while True:
                response = await matrix.sync(timeout=30000, since=next_batch)
                next_batch = response.next_batch
                room = response.rooms.join.get(room_id)
                if not room:
                    continue
                for ev in room.timeline.events:
                    if isinstance(ev, RoomMessageText) and ev.sender != matrix.user_id:
                        out = f"{ev.body}"[:134]  # LoRa ist kurz
                        print(f"[Matrix -> Mesh]: {out}")
                        await mc.commands.send_chan_msg(channel_idx, out)

        print(f"🚀 Bridge läuft (Kanal '{MESH_CHANNEL_NAME}' = Index {channel_idx}). "
              f"Strg+C zum Beenden.")
        await matrix_listener()

    finally:
        if mc is not None:
            await mc.disconnect()
        await matrix.close()
        print("Verbindungen geschlossen.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBridge sauber beendet.")
