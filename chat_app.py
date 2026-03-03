import subprocess
import threading
import json
import socket
import psutil
import ipaddress


PORT = 12487

# Dynamic dictionary to hold discovered peers
known_peers = {}


def get_network_details():
    """Dynamically finds the local IP and uses nmap to find active hosts in the subnet."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        my_ip = s.getsockname()[0]
        s.close()
    except Exception:
        return "127.0.0.1", []

    active_hosts = []
    # Match the IP to the correct network interface to find its subnet mask
    for interface_name, interface_addresses in psutil.net_if_addrs().items():
        for addr in interface_addresses:
            if addr.family == socket.AF_INET and addr.address == my_ip:
                netmask = addr.netmask
                
                # Use ipaddress to calculate the exact network bounds
                network = ipaddress.IPv4Network(f"{my_ip}/{netmask}", strict=False)
                
                print(f"[*] Scanning network {network} with nmap. This might take a moment...")
                try:
                    nmap_result = subprocess.run(
                        ['nmap', '-sn', '-oG', '-', str(network)], 
                        capture_output=True, 
                        text=True
                    )
                    for line in nmap_result.stdout.splitlines():
                        if "Status: Up" in line and line.startswith("Host:"):
                            ip = line.split(" ")[1]
                            active_hosts.append(ip)
                except FileNotFoundError:
                    print("[!] nmap is not installed or not in PATH.")
                except Exception as e:
                    print(f"[!] Error running nmap: {e}")
                    
                return my_ip, active_hosts
                
    return my_ip, active_hosts

# --- SENDING FUNCTIONS ---

def send_via_tcp(ip, port, message, timeout=2):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if timeout:
            s.settimeout(timeout)
        try:
            s.connect((ip, port))
            s.sendall(message.encode('utf-8'))
        except socket.error:
            pass

def send_type_message(destination_ip, destination_port, sender_name, sender_ip, payload):
    message_dict = {
        "type": "MESSAGE",
        "SENDER_IP": sender_ip,
        "SENDER_NAME": sender_name,
        "PAYLOAD": payload
    }
    send_via_tcp(destination_ip, destination_port, json.dumps(message_dict))

def send_type_ask(destination_ip, destination_port, sender_ip):
    message_dict = {
        "type": "ASK",
        "SENDER_IP": sender_ip
    }
    # Keep short timeout for scanning; on macOS -G handles connect timeout
    send_via_tcp(destination_ip, destination_port, json.dumps(message_dict))

def send_type_reply(destination_ip, destination_port, my_name, my_ip):
    message_dict = {
        "type": "REPLY",
        "RECEIVER_NAME": my_name,
        "RECEIVER_IP": my_ip
    }
    send_via_tcp(destination_ip, destination_port, json.dumps(message_dict))

# --- LISTENING FUNCTION ---
def listen_for_messages(my_name, my_ip, my_port):
    """Runs in the background to listen for incoming tcp connections."""
    print(f"[*] Listening for incoming messages on {my_ip}:{my_port}...")
    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((my_ip, PORT))
        s.listen()
        while True:
            conn, addr = s.accept() 
            with conn: 
                buffer = bytearray()
                while True:
                    chunk = conn.recv(1024)
                    if not chunk:
                        break
                    buffer.extend(chunk)
                
                if buffer:
                    full_message = buffer.decode("utf-8")
                    handle_received_message(full_message, my_name, my_ip)
            

def handle_received_message(raw_message: str, my_name, my_ip):
    raw_message = raw_message.strip()
    
    try:
        data = json.loads(raw_message)
        msg_type = data.get("type")
        
        if msg_type == "MESSAGE":
            sender = data.get("SENDER_NAME", "Unknown")
            payload = data.get("PAYLOAD", "")
            print(f"\r\033[K[{sender}]: {payload}")
            print("You (Format -> ReceiverName: Message): ", end="", flush=True) 
            
        elif msg_type == "ASK":
            sender_ip = data.get("SENDER_IP")
            if sender_ip:
                t = threading.Thread(target=send_type_reply, args=(sender_ip, PORT, my_name, my_ip), daemon=True)
                t.start()
                
        elif msg_type == "REPLY":
            peer_name = data.get("RECEIVER_NAME")
            peer_ip = data.get("RECEIVER_IP")
            if peer_name and peer_ip and peer_name != my_name:
                known_peers[peer_name] = peer_ip
                print(f"\r\033[K[*] Discovered {peer_name} at {peer_ip}!")
                print("You (Format -> ReceiverName: Message): ", end="", flush=True) 
                
    except json.JSONDecodeError:
        print(f"\r\033[K[Raw Text Received]: {raw_message}")
        print("You (Format -> ReceiverName: Message): ", end="", flush=True)



# --- MAIN APPLICATION BLOCK ---
if __name__ == "__main__":
    my_name = input("Enter your username: ").strip()
    
    my_ip, active_hosts = get_network_details()
    known_peers[my_name] = my_ip

    listener_thread = threading.Thread(target=listen_for_messages, args=(my_name, my_ip, PORT), daemon=True)
    listener_thread.start()

    print(f"\nLogged in as {my_name} (IP: {my_ip}). Chat started!")
    print("Type 'quit' to leave, or 'discover' to scan the network.")
    
    while True:
        try:
            message = input("You (Format -> ReceiverName: Message): ")
            
            if message.lower() in ['quit', 'exit']:
                print("Exiting chat...")
                break
                
            if message.lower() == 'discover':
                my_ip, active_hosts = get_network_details()
                if active_hosts:
                    print(f"[*] Broadcasting 'ask' messages to active hosts ...")
                    for target_ip in active_hosts:
                        if target_ip != my_ip:
                            t = threading.Thread(target=send_type_ask, args=(target_ip, PORT, my_ip), daemon=True)
                            t.start()
                else:
                    print("[!] No active hosts found or could not determine subnet bounds.")
                continue
            
            if message.strip():
                if ':' in message:
                    receiver_name, content = message.split(':', 1)
                    receiver_name = receiver_name.strip()
                    content = content.strip()
                    
                    payload_size = len(content.encode('utf-8'))
                    if payload_size > 2048:
                        print(f"[!] Message rejected: Payload is too large ({payload_size} bytes). Maximum allowed is 2048 bytes.")
                        continue
                    
                    receiver_ip = known_peers.get(receiver_name)
                    
                    if receiver_ip:
                        t = threading.Thread(target=send_type_message, args=(receiver_ip, PORT, my_name, my_ip, content), daemon=True)
                        t.start()
                    else:
                        print(f"User '{receiver_name}' not found. Type 'discover' first!")
                else:
                    print("Invalid format. Please use 'ReceiverName: Your message here'.")
                    
        except KeyboardInterrupt:
            print("\nExiting chat...")
            break