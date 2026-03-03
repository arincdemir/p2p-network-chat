How to run:

nmap should be installed in your system

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 p2p_app.py


How to use:

Run python3 p2p_app.py and enter your username. The app will automatically scan your network for active peers.
Click a peer's name in the right sidebar to focus on them, type your message in the bottom input bar, and press Enter.
Press Ctrl+D to manually rescan for new peers (and remove disconnected ones).
Press Ctrl+Q to safely quit the app.


I tested this code with my friend Dağhan Erdönmez's implementation. 
!!! However, he used the port 12345 on the code he uploaded. Mine uses 12487 like many other people. One of them needs to be changed at the code's header.
My code is tested on Ubuntu.

!!! I forgot to take a screenshot when I was trying with daghan. So I replicated the scenario on my computer to get a screenshot.
That is why the ip numbers are different in the pcap file and the screenshot.

