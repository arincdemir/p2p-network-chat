#CONFIGURATION

PORT = 12345 # Change this variable to change the port to be used for communication.

#CONFIGURATION

import threading
import json
import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
import nmap

username = ""
ip_chatting = None
chatting_name = None
menuextra = ""

known_users = {}
known_users_chats = {}

stop_event = threading.Event()

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect(("8.8.8.8", 80))
my_ip = s.getsockname()[0]
s.close()

listener_sock = None
listener_lock = threading.Lock()

def find_all_hosts():
    nm = nmap.PortScanner()
    nm.scan(hosts=f"{my_ip}/24", arguments="-sn")
    return nm.all_hosts()
    
def message_packet(message: str):
    return {
            "type": "MESSAGE",
            "PAYLOAD": message,
            "SENDER_NAME": username,
            "SENDER_IP": my_ip
        }

def send_packet(ip: str, packet: dict):
    if packet.get("type") == "MESSAGE":
        payload = str(packet.get("PAYLOAD", ""))
        payload_size = len(payload.encode("utf-8"))
        if payload_size > 2048:
            print(f"Message too large ({payload_size} bytes). Max allowed is 2048 bytes.")
            return False

    raw = json.dumps(packet)
    try:
        with socket.create_connection((ip, PORT), timeout=1.0) as s:
            s.sendall((raw + "\n").encode("utf-8"))
        return True
    except OSError:
        return False

def send_ask(ip: str):
    packet = {
        "type": "ASK",
        "SENDER_IP": my_ip
    }
    send_packet(ip, packet)

def discover(all_hosts, my_ip):
    targets = [ip for ip in all_hosts if ip != my_ip]

    with ThreadPoolExecutor(max_workers=64) as ex:
        futures = {ex.submit(send_ask, ip): ip for ip in targets}

        for f in as_completed(futures):
            ip = futures[f]
            try:
                f.result()
            except Exception as e:
                print(f"discover error {ip}: {e}")

    print(known_users)

def handle_received_packet(packet: str):
    #print("a")
    try:
        packet = json.loads(packet)
    except json.decoder.JSONDecodeError:
        #print("evet json error")
        return
    if packet["type"] == "ASK":
        #print("b")
        reply = {
            "type": "REPLY",
            "RECEIVER_NAME": username,
            "RECEIVER_IP": my_ip
        }
        send_packet(packet["SENDER_IP"], reply)
    elif packet["type"] == "REPLY":
        #print("f")
        receiver_name = packet["RECEIVER_NAME"]
        receiver_ip = packet["RECEIVER_IP"]
        if receiver_ip not in known_users:
            known_users[receiver_ip] = receiver_name
            known_users_chats.setdefault(receiver_ip, [])
            print(f'Discovered {receiver_name} @ {receiver_ip}')
        elif known_users[receiver_ip] != receiver_name:
            print(f'Discovered {receiver_name} @ {receiver_ip}, [Address was previously used by {known_users[receiver_ip]}]')
            known_users[receiver_ip] = receiver_name
            known_users_chats.setdefault(receiver_ip, [])
        else:
            pass
    elif packet["type"] == "MESSAGE":
        #print("d")
        sender_ip = packet["SENDER_IP"]
        sender_name = packet["SENDER_NAME"]
        payload = packet["PAYLOAD"]
        known_users_chats.setdefault(sender_ip, []).append((sender_name, payload))
        #print(f'{sender_name}: {payload}')
        if state == 1:
            clear_window()
            render_chat()

    else:
        pass
        #print("handleelse")


def listen_loop():
    global listener_sock
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(("", PORT))
        server_sock.listen()
        server_sock.settimeout(1.0)

        with listener_lock:
            listener_sock = server_sock

        while not stop_event.is_set():
            try:
                conn, addr = server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            with conn:
                chunks = []
                while True:
                    data = conn.recv(4096)
                    if not data:
                        break
                    chunks.append(data)
                    if b"\n" in data:
                        break

                raw = b"".join(chunks).decode("utf-8", errors="replace").strip()
                if raw:
                    handle_received_packet(raw)

        with listener_lock:
            if listener_sock is server_sock:
                listener_sock = None

def stop_listener_socket():
    with listener_lock:
        sock = listener_sock
    if sock:
        try:
            sock.close()
        except OSError:
            pass

def clear_window():
    print("\x1b[2J\x1b[H", end="")

def render_menu():
    print("487 Chat App")
    print("Write '\quit' to quit")
    print("Write '\discover' to discover new users around you.")
    print("Write the name of a user to chat with them.")
    print(menuextra)
    print()
    print("Users you already know:")
    print(known_users)

def render_chat():
    print("Chatting with", chatting_name)
    print("Type '\menu' to return to menu or '\quit' to quit.")
    print()
    if ip_chatting is None:
        return

    for sender_name, message in known_users_chats.get(ip_chatting, []):
        print(f"{sender_name}: {message}")


def find_ip(users, username):
    return next((ip for ip, user in users.items() if user == username), None)

def main():
    global username
    global chatting_name
    global ip_chatting
    global menuextra
    global state

    t = None
    try:
        clear_window()
        
        while not username:
            username = input("Enter username: ").strip()
            if not username:
                print("Username cannot be empty.")

        state = 0
        #send_packet("192.168.0.24", mock_packet)
        #discover()

        t = threading.Thread(target=listen_loop, daemon=True)
        t.start()

        while True:
            if state == 0:
                clear_window()
                render_menu()
            elif state == 1:
                clear_window()
                render_chat()

            cmd = input("> ").strip()
            menuextra = ""
            if state == 0:
                if cmd == "\quit":
                    break
                elif cmd == "\discover":
                    all_hosts = find_all_hosts()
                    #print(all_hosts)
                    discover(all_hosts, my_ip)
                else:
                    ip_chatting = find_ip(known_users, cmd)
                    if ip_chatting is not None:
                        state = 1
                        chatting_name = cmd
                        known_users_chats.setdefault(ip_chatting, [])
                    else:
                        menuextra = "No user with name " + cmd
                    #send_packet(other_ip, mock_packet)
            elif state == 1:
                if cmd == "\quit":
                    break
                elif cmd == "\menu":
                    state = 0
                else:
                    sent = send_packet(ip_chatting, message_packet(cmd))
                    if sent:
                        known_users_chats.setdefault(ip_chatting, []).append((username, cmd))

    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        stop_listener_socket()
        if t is not None:
            t.join(timeout=2)

main()
