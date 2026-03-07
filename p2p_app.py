import threading
import json
import socket
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Input, RichLog, Label, ListView, ListItem
from typing import Dict, List, Tuple, Optional
import time

PORT: int = 12487
known_peers: Dict[str, Tuple[str, float]] = {}
# known_peers structure:
#   key   : str   -> peer name
#   value : [str, float] -> [peer IP address, last_seen timestamp]
# Example: {"Alice": ["192.168.1.10", 1700000000]}
ASK_PERIOD: float = 1.0
KNOWN_PEER_TIMEOUT: float = 4.0
peers_lock: threading.Lock = threading.Lock()

# --- NETWORK DISCOVERY ---
def get_my_ip() -> str:
    """Gets the local IP address without relying on an active internet connection."""
    
    # Local Broadcast (Works offline on a LAN)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # Connecting to a broadcast address forces the OS to pick the local LAN interface
        s.connect(("255.255.255.255", 1))
        my_ip = s.getsockname()[0]
        s.close()
        # Ensure we didn't accidentally grab a loopback address
        if my_ip and not my_ip.startswith("127."):
            return my_ip
    except Exception:
        pass

    # The Google DNS hack (Works if there's a default internet gateway)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        my_ip = s.getsockname()[0]
        s.close()
        return my_ip
    except Exception:
        pass

    # The fallback
    return "127.0.0.1"

# --- NETWORK SENDING FUNCTIONS ---
def send_via_tcp(ip: str, port: int, message: str, timeout: int = 2) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if timeout:
            s.settimeout(timeout)
        try:
            s.connect((ip, port))
            s.sendall(message.encode('utf-8'))
            return True
        except socket.error:
            return False
        
def broadcast_via_udp(port: int, message: str) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        broadcast_addr = ("255.255.255.255", port)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(message.encode('utf-8'), broadcast_addr)

def send_type_message(destination_ip: str, destination_port: int, sender_name: str, sender_ip: str, payload: str) -> bool:
    message_dict = {"type": "MESSAGE", "SENDER_IP": sender_ip, "SENDER_NAME": sender_name, "PAYLOAD": payload}
    return send_via_tcp(destination_ip, destination_port, json.dumps(message_dict))

def send_type_ask(destination_port: int, sender_ip: str) -> None:
    message_dict = {"type": "ASK", "SENDER_IP": sender_ip}
    broadcast_via_udp( destination_port, json.dumps(message_dict))

def send_type_reply(destination_ip: str, destination_port: int, my_name: str, my_ip: str) -> None:
    message_dict = {"type": "REPLY", "RECEIVER_NAME": my_name, "RECEIVER_IP": my_ip}
    send_via_tcp(destination_ip, destination_port, json.dumps(message_dict))

# --- TEXTUAL APPLICATION ---
class P2PChatApp(App):
    """A Textual app for P2P messaging with chat tabs and toast notifications."""
    
    ENABLE_COMMAND_PALETTE = False 

    CSS = """
    Screen { background: $surface; }
    #chat-pane { width: 75%; height: 100%; border-right: solid $primary; }
    #sidebar { width: 25%; height: 100%; padding: 1; }
    #chat-log { height: 1fr; padding: 1; }
    #message-input { dock: bottom; margin: 1; }
    """

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, my_name: str, my_ip: str) -> None:
        super().__init__()
        self.my_name: str = my_name
        self.my_ip: str = my_ip
        self.active_hosts: List[str] = []
        
        # --- STATE MANAGEMENT ---
        self.active_peer: Optional[str] = None 
        self.chat_history: Dict[str, List[str]] = {} 

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="chat-pane"):
                yield RichLog(id="chat-log", highlight=True, markup=True)
                yield Input(placeholder="Select a peer from the sidebar to start chatting...", id="message-input")
            with Vertical(id="sidebar"):
                yield Label("[b]Active Peers[/b]\n(Click to Focus)\n")
                yield ListView(id="peers-list")
        yield Footer()

    def on_mount(self) -> None:
        self.chat_log = self.query_one("#chat-log", RichLog)
        self.peers_list = self.query_one("#peers-list", ListView)
        
        self.update_peers_list()
        
        self.notify(f"Logged in as {self.my_name} (IP: {self.my_ip}).", title="System", severity="information")
        
        message_listener_thread = threading.Thread(target=self.listen_for_messages, daemon=True)
        message_listener_thread.start()

        ask_listener_thread = threading.Thread(target=self.listen_for_asks, daemon=True)
        ask_listener_thread.start()

        discovery_thread = threading.Thread(target=self.periodic_discover_and_cleanup, daemon=True)
        discovery_thread.start()

    # --- UI EVENT HANDLERS ---
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.active_peer = getattr(event.item, "peer_name", None)
        self.chat_log.clear()
        
        input_widget = self.query_one(Input)
        if self.active_peer:
            input_widget.placeholder = f"Message {self.active_peer}..."
            
            if self.active_peer in self.chat_history:
                for msg in self.chat_history[self.active_peer]:
                    self.chat_log.write(msg)

    async def on_input_submitted(self, message: Input.Submitted) -> None:
        raw_msg = message.value
        if not raw_msg.strip(): return
            
        self.query_one(Input).value = ""

        receiver_name = None
        content = raw_msg

        if self.active_peer:
            receiver_name = self.active_peer
        elif ':' in raw_msg:
            receiver_name, content = raw_msg.split(':', 1)
            receiver_name, content = receiver_name.strip(), content.strip()
            
        if not receiver_name:
            self.notify("Click a peer to focus, or use 'ReceiverName: Message'.", title="Error", severity="error")
            return

        with peers_lock:
            peer_entry = known_peers.get(receiver_name)
            receiver_ip = peer_entry[0] if peer_entry else None
        if receiver_ip:
            t = threading.Thread(target=self._send_message_worker, args=(receiver_name, receiver_ip, content), daemon=True)
            t.start()
        else:
            self.notify(f"User '{receiver_name}' not found. Peers are discovered automatically.", title="Error", severity="error")

    # --- UI LOGGING / STATE UPDATE METHODS ---
    def _store_and_print(self, tab_name: str, msg_markup: str) -> None:
        if tab_name not in self.chat_history:
            self.chat_history[tab_name] = []
        self.chat_history[tab_name].append(msg_markup)
        
        if self.active_peer == tab_name:
            self.chat_log.write(msg_markup)

    def log_system(self, text: str, is_error: bool = False) -> None:
        severity = "error" if is_error else "information"
        self.notify(text, title="System", severity=severity)

    def log_message(self, tab_name: str, display_name: str, text: str, is_me: bool = False) -> None:
        color = "cyan" if is_me else "green"
        self._store_and_print(tab_name, f"[[{color}]{display_name}[/{color}]] {text}")

    def update_peers_list(self) -> None:
        self.peers_list.clear()
        with peers_lock:
            peers_snapshot = dict(known_peers)
        for name, (ip, _last_seen) in peers_snapshot.items():
            if name != self.my_name:
                item = ListItem(Label(f"👤 {name}\n  [dim]{ip}[/dim]"))
                item.peer_name = name
                self.peers_list.append(item)

    # --- ACTIONS & BACKGROUND WORKERS ---
    def periodic_discover_and_cleanup(self) -> None:
        """Periodically broadcasts ASK and removes peers that have timed out."""
        while True:
            send_type_ask(PORT, self.my_ip)

            now = time.time()
            removed = []
            with peers_lock:
                stale = [name for name, (ip, last_seen) in known_peers.items()
                         if now - last_seen > KNOWN_PEER_TIMEOUT]
                for name in stale:
                    del known_peers[name]
                    removed.append(name)

            if removed:
                for name in removed:
                    self.call_from_thread(self.log_system, f"{name} timed out and was removed.")
                self.call_from_thread(self.update_peers_list)
                if self.active_peer in removed:
                    self.active_peer = None
                    self.call_from_thread(self.chat_log.clear)
                    input_widget = self.query_one(Input)
                    self.call_from_thread(
                        setattr, input_widget, "placeholder",
                        "Select a peer from the sidebar to start chatting..."
                    )

            time.sleep(ASK_PERIOD)

    def _send_message_worker(self, receiver_name: str, receiver_ip: str, content: str) -> None:
        success = send_type_message(receiver_ip, PORT, self.my_name, self.my_ip, content)
        
        if success:
            self.call_from_thread(self.log_message, receiver_name, "You", content, is_me=True)
        else:
            self.call_from_thread(self.log_system, f"Failed to deliver to {receiver_name}. They may have disconnected.", is_error=True)
            with peers_lock:
                known_peers.pop(receiver_name, None)
            self.call_from_thread(self.update_peers_list)

    # --- LISTENING FUNCTION FOR TCP MESSAGES ---
    def listen_for_messages(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.my_ip, PORT))
            s.listen()
            while True:
                conn, addr = s.accept() 
                with conn: 
                    buffer = bytearray()
                    while True:
                        chunk = conn.recv(1024)
                        if not chunk: break
                        buffer.extend(chunk)
                    
                    if buffer:
                        self.handle_received_message(buffer.decode("utf-8"))

    # --- UDP LISTEN FUNCTION FOR ASK BROADCASTS ---
    def listen_for_asks(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.bind(("0.0.0.0", PORT))
            while True:
                data, addr = s.recvfrom(1024)
                self.handle_received_ask(data.decode("utf-8"))

    def handle_received_ask(self, raw_message: str) -> None:
        try:
            data = json.loads(raw_message.strip())
            msg_type = data.get("type")

            if msg_type == "ASK":
                sender_ip = data.get("SENDER_IP")
                if sender_ip and sender_ip != self.my_ip:
                    t = threading.Thread(target=send_type_reply, args=(sender_ip, PORT, self.my_name, self.my_ip), daemon=True)
                    t.start()

        except json.JSONDecodeError:
            self.call_from_thread(self.log_system, f"Raw Text Received: {raw_message}", is_error=True)


    def handle_received_message(self, raw_message: str) -> None:
        try:
            data = json.loads(raw_message.strip())
            msg_type = data.get("type")
            
            if msg_type == "MESSAGE":
                sender = data.get("SENDER_NAME", "Unknown")
                payload = data.get("PAYLOAD", "")
                self.call_from_thread(self.log_message, sender, sender, payload)
                    
            elif msg_type == "REPLY":
                peer_name = data.get("RECEIVER_NAME")
                peer_ip = data.get("RECEIVER_IP")
                if peer_name and peer_ip and peer_name != self.my_name:
                    with peers_lock:
                        is_new = peer_name not in known_peers
                        known_peers[peer_name] = (peer_ip, time.time())
                    if is_new:
                        self.call_from_thread(self.log_system, f"Discovered {peer_name} at {peer_ip}!")
                    self.call_from_thread(self.update_peers_list)
                    
        except json.JSONDecodeError:
            self.call_from_thread(self.log_system, f"Raw Text Received: {raw_message}", is_error=True)

if __name__ == "__main__":
    my_name: str = input("Enter your username: ").strip()
    
    my_ip: str = get_my_ip()
    app = P2PChatApp(my_name, my_ip)
    app.run()