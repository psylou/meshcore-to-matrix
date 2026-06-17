import asyncio
import os
import re
import html as html_lib
from meshcore import MeshCore, EventType
from nio import (
    AsyncClient, LoginResponse,
    RoomResolveAliasResponse, RoomMessageText,
)
from dotenv import load_dotenv
load_dotenv()

sent_messages = {}  # event_id -> mesh_name

# === CONFIG ===
MATRIX_HOMESERVER = os.environ.get("MATRIX_HOMESERVER")
MATRIX_BOT_USER   = os.environ["MATRIX_BOT_USER"]
MATRIX_PASSWORD   = os.environ["MATRIX_PASSWORD"]
MATRIX_ROOM_ALIAS = os.environ.get("MATRIX_ROOM")
MESH_HOST = os.environ.get("MESH_HOST")
MESH_PORT = int(os.environ.get("MESH_PORT"))
MESH_CHANNEL_NAME = os.environ.get("MESH_CHANNEL_NAME")
MAX_CHANNELS = 16
# ==============


async def find_channel_idx(mc, name: str):
    """Sucht den Kanal-Index anhand des Namens."""
    target = name.lstrip("#").strip().lower()
    for idx in range(MAX_CHANNELS):
        res = await mc.commands.get_channel(idx)
        info = res.payload if hasattr(res, "payload") else res
        if not info:
            continue
        ch_name = ""
        if isinstance(info, dict):
            ch_name = info.get("channel_name") or info.get("name") or ""
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

        # --- Kanal-Index per Name ---
        channel_idx = await find_channel_idx(mc, MESH_CHANNEL_NAME)
        if channel_idx is None:
            print(f"❌ Kanal '{MESH_CHANNEL_NAME}' nicht gefunden.")
            return

        # === RICHTUNG 1: MeshCore -> Matrix ===
        async def on_channel_msg(event):
            p = event.payload
            ch = p.get("channel_idx")
            if ch != channel_idx:
                return
            raw = p.get("text", "")
            if ": " in raw:
                sender, msg = raw.split(": ", 1)
            else:
                sender, msg = "?", raw

            sender_e = html_lib.escape(sender)
            msg_e = html_lib.escape(msg)
            plain = f"[{sender}] {msg}"
            html_body = (f'<font color="#1a73e8"><b>[{sender_e}]</b></font> '
                         f'{msg_e}')

            print(f"[Mesh -> Matrix] ({ch}): {raw}")
            resp = await matrix.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": plain,
                    "format": "org.matrix.custom.html",
                    "formatted_body": html_body,
                },
            )
            if hasattr(resp, "event_id"):
                sent_messages[resp.event_id] = sender
                if len(sent_messages) > 500:
                    sent_messages.pop(next(iter(sent_messages)))

        # --- Reply-Parsing ---
        async def parse_matrix_message(ev):
            content = ev.source.get("content", {})
            body = content.get("body", "")
            rel = content.get("m.relates_to", {})
            reply_to = rel.get("m.in_reply_to", {}).get("event_id")

            if not reply_to:
                return body

            mesh_name = sent_messages.get(reply_to)
            if not mesh_name:
                orig = await matrix.room_get_event(room_id, reply_to)
                if hasattr(orig, "event") and orig.event:
                    orig_body = orig.event.source.get("content", {}).get("body", "")
                    m = re.search(r"\[([^\]]+)\]", orig_body)
                    if m:
                        mesh_name = m.group(1)

            if mesh_name:
                return f"@[{mesh_name}] {body}"
            return body

        # --- Events registrieren ---
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
                        text = await parse_matrix_message(ev)
                        out = f"{text}"[:134]
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
