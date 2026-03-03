FROM ubuntu:latest

# Install python and pip
RUN apt update && \
    apt install -y python3 python3-pip python3-venv && \
    apt clean all

# Create a virtual environment in /opt/venv
RUN python3 -m venv /opt/venv

# Make sure the virtual environment is used for all subsequent commands
# by putting its bin directory at the front of the PATH
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .

# Install dependencies into the virtual environment
RUN pip install -r requirements.txt

# Set the working directory inside the container
WORKDIR /app

# Copy your python script into the container
COPY p2p_app.py .


# Run the script when the container starts
# (This will automatically use the venv's python3 due to the ENV PATH above)
CMD ["python3", "-u", "p2p_app.py"]