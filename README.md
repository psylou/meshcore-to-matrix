# MeshCore ↔ Matrix Bridge
## Bridges a MeshCore channel with a Matrix room in both directions.

_works on my machine._

## Capabilities:

- Message from Matrix room to Meshcore channel
- Message from Meshcore Channel to Matrix room
- ReplyTo Message in Matrix uses the @[MeshCore-User] reply in MeshCore

### Setup (Docker Compose)

```yml
services:
  meshcore-matrix-bridge:
    image: ghcr.io/psylou/meshcore-bridge:latest
    container_name: meshcore-matrix-bridge
    restart: unless-stopped
    environment:
      MATRIX_HOMESERVER: "https://matrix.example.com"
      MATRIX_BOT_USER: "@meshcorebot:example.com"
      MATRIX_PASSWORD: "Password"
      MATRIX_ROOM: "#erfurt-meshcore:example.com"
      MESH_HOST: "IP"
      MESH_PORT: "4404"
      MESH_CHANNEL_NAME: "erfurt"
```

### Requirements:
Bot user exists on the homeserver and is in the room.
Companion has joined the MeshCore channel.
MESH_HOST is reachable from the container.

PS: Sorry, comments are german.
