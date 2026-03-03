import subprocess
import threading
import json
import socket
import psutil
import ipaddress
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Input, RichLog, Label, ListView, ListItem

PORT = 12487
known_peers = {}

# --- NETWORK DISCOVERY ---
def get_my_ip():
    """Instantly gets the local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        my_ip = s.getsockname()[0]
        s.close()
        return my_ip
    except Exception:
        return "127.0.0.1"

def get_active_hosts(my_ip):
    """Runs the slow nmap scan to find other active machines."""
    active_hosts = []
    for interface_name, interface_addresses in psutil.net_if_addrs().items():
        for addr in interface_addresses:
            if addr.family == socket.AF_INET and addr.address == my_ip:
                netmask = addr.netmask
                network = ipaddress.IPv4Network(f"{my_ip}/{netmask}", strict=False)
                try:
                    nmap_result = subprocess.run(
                        ['nmap', '-sn', '-oG', '-', str(network)], 
                        capture_output=True, text=True
                    )
                    for line in nmap_result.stdout.splitlines():
                        if "Status: Up" in line and line.startswith("Host:"):
                            ip = line.split(" ")[1]
                            active_hosts.append(ip)
                except Exception:
                    pass
                return active_hosts
    return active_hosts

# --- NETWORK SENDING FUNCTIONS ---
def send_via_tcp(ip, port, message, timeout=2):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if timeout:
            s.settimeout(timeout)
        try:
            s.connect((ip, port))
            s.sendall(message.encode('utf-8'))
            return True
        except socket.error:
            return False

def send_type_message(destination_ip, destination_port, sender_name, sender_ip, payload):
    message_dict = {"type": "MESSAGE", "SENDER_IP": sender_ip, "SENDER_NAME": sender_name, "PAYLOAD": payload}
    return send_via_tcp(destination_ip, destination_port, json.dumps(message_dict))

def send_type_ask(destination_ip, destination_port, sender_ip):
    message_dict = {"type": "ASK", "SENDER_IP": sender_ip}
    send_via_tcp(destination_ip, destination_port, json.dumps(message_dict))

def send_type_reply(destination_ip, destination_port, my_name, my_ip):
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
        ("ctrl+d", "discover", "Discover Peers"),
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, my_name, my_ip):
        super().__init__()
        self.my_name = my_name
        self.my_ip = my_ip
        self.active_hosts = []
        
        # --- STATE MANAGEMENT ---
        self.active_peer = None 
        self.chat_history = {} 

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

    def on_mount(self) -> ComposeResult:
        self.chat_log = self.query_one("#chat-log", RichLog)
        self.peers_list = self.query_one("#peers-list", ListView)
        
        self.update_peers_list()
        
        self.notify(f"Logged in as {self.my_name} (IP: {self.my_ip}).", title="System", severity="information")
        
        listener_thread = threading.Thread(target=self.listen_for_messages, daemon=True)
        listener_thread.start()
        
        # Automatically trigger a background scan so the user doesn't have to wait or press Ctrl+D
        self.action_discover()

    # --- UI EVENT HANDLERS ---
    def on_list_view_selected(self, event: ListView.Selected):
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

        if receiver_name in known_peers:
            receiver_ip = known_peers[receiver_name]
            t = threading.Thread(target=self._send_message_worker, args=(receiver_name, receiver_ip, content), daemon=True)
            t.start()
        else:
            self.notify(f"User '{receiver_name}' not found. Press Ctrl+D to discover.", title="Error", severity="error")

    # --- UI LOGGING / STATE UPDATE METHODS ---
    def _store_and_print(self, tab_name: str, msg_markup: str):
        if tab_name not in self.chat_history:
            self.chat_history[tab_name] = []
        self.chat_history[tab_name].append(msg_markup)
        
        if self.active_peer == tab_name:
            self.chat_log.write(msg_markup)

    def log_system(self, text: str, is_error=False):
        severity = "error" if is_error else "information"
        self.notify(text, title="System", severity=severity)

    def log_message(self, tab_name: str, display_name: str, text: str, is_me=False):
        color = "cyan" if is_me else "green"
        self._store_and_print(tab_name, f"[[{color}]{display_name}[/{color}]] {text}")

    def update_peers_list(self):
        self.peers_list.clear()
        for name, ip in known_peers.items():
            if name != self.my_name:
                item = ListItem(Label(f"👤 {name}\n  [dim]{ip}[/dim]"))
                item.peer_name = name
                self.peers_list.append(item)

    # --- ACTIONS & BACKGROUND WORKERS ---
    def action_discover(self) -> None:
        self.log_system("Scanning network for peers in the background...")
        
        def _scan_and_send():
            self.active_hosts = get_active_hosts(self.my_ip)
            
            stale_peers = []
            for name, ip in known_peers.items():
                if name != self.my_name and ip not in self.active_hosts:
                    stale_peers.append(name)
                    
            for name in stale_peers:
                del known_peers[name]
                self.call_from_thread(self.log_system, f"Peer {name} has left the network.")
                
            if stale_peers:
                self.call_from_thread(self.update_peers_list)

            for target_ip in self.active_hosts:
                if target_ip != self.my_ip:
                    t = threading.Thread(target=send_type_ask, args=(target_ip, PORT, self.my_ip), daemon=True)
                    t.start()
                    
        threading.Thread(target=_scan_and_send, daemon=True).start()

    def _send_message_worker(self, receiver_name, receiver_ip, content):
        success = send_type_message(receiver_ip, PORT, self.my_name, self.my_ip, content)
        
        if success:
            self.call_from_thread(self.log_message, receiver_name, "You", content, is_me=True)
        else:
            self.call_from_thread(self.log_system, f"Failed to deliver to {receiver_name}. They may have disconnected.", is_error=True)
            if receiver_name in known_peers:
                del known_peers[receiver_name]
                self.call_from_thread(self.update_peers_list)

    # --- LISTENING FUNCTION ---
    def listen_for_messages(self):
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

    def handle_received_message(self, raw_message: str):
        try:
            data = json.loads(raw_message.strip())
            msg_type = data.get("type")
            
            if msg_type == "MESSAGE":
                sender = data.get("SENDER_NAME", "Unknown")
                payload = data.get("PAYLOAD", "")
                self.call_from_thread(self.log_message, sender, sender, payload)
                
            elif msg_type == "ASK":
                sender_ip = data.get("SENDER_IP")
                if sender_ip:
                    t = threading.Thread(target=send_type_reply, args=(sender_ip, PORT, self.my_name, self.my_ip), daemon=True)
                    t.start()
                    
            elif msg_type == "REPLY":
                peer_name = data.get("RECEIVER_NAME")
                peer_ip = data.get("RECEIVER_IP")
                if peer_name and peer_ip and peer_name != self.my_name:
                    if peer_name not in known_peers:
                        self.call_from_thread(self.log_system, f"Discovered {peer_name} at {peer_ip}!")
                    known_peers[peer_name] = peer_ip
                    self.call_from_thread(self.update_peers_list)
                    
        except json.JSONDecodeError:
            self.call_from_thread(self.log_system, f"Raw Text Received: {raw_message}", is_error=True)

if __name__ == "__main__":
    my_name = input("Enter your username: ").strip()
    
    my_ip = get_my_ip()
    known_peers[my_name] = my_ip

    app = P2PChatApp(my_name, my_ip)
    app.run()