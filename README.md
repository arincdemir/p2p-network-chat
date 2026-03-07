# P2P Network Chat

A peer-to-peer chat application that discovers other users on the local network and allows direct messaging between them. Peers are discovered via UDP broadcast, and messages are exchanged over TCP using a simple JSON protocol.

- **`p2p_app.py`** — A terminal UI built with [Textual](https://github.com/Textualize/textual), featuring a sidebar with discovered peers, per-peer chat history, and toast notifications.

## Prerequisites

- Python 3

## Setup

```sh
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage

```sh
python3 p2p_app.py
```

1. Enter your username when prompted.
2. The app scans the local network for active peers.
3. Click a peer's name in the sidebar to open a chat.
4. Type a message in the input bar and press **Enter** to send.

### Key Bindings

| Key | Action |
| --- | --- |
| `Ctrl+Q` | Quit the application |

## Docker

You can test with multiple peers using Docker containers on an isolated network:

```sh
# Build the image
docker build -t p2p-chat .

# Create a shared network
docker network create --subnet=172.20.0.0/24 my-chat-net

# Start peers in separate terminals
docker run -it --name alice --net my-chat-net p2p-chat
docker run -it --name bob   --net my-chat-net p2p-chat

# Clean up
docker rm -f alice bob
docker network rm my-chat-net
```

## Protocol

Peers communicate on port `12487` using JSON messages. Three message types are used:

### ASK (UDP broadcast)

Broadcast to the local network to request identification from all peers.

```json
{ "type": "ASK", "SENDER_IP": "192.168.1.10" }
```

### REPLY (TCP)

Sent back to the ASK sender via TCP, carrying the responder's username and IP.

```json
{ "type": "REPLY", "RECEIVER_NAME": "alice", "RECEIVER_IP": "192.168.1.20" }
```

### MESSAGE (TCP)

A direct chat message sent via TCP.

```json
{ "type": "MESSAGE", "SENDER_IP": "192.168.1.10", "SENDER_NAME": "bob", "PAYLOAD": "Hello!" }
```

## License

This project is licensed under the [MIT License](LICENSE)
