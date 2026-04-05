import logging
import os
import urllib3
import requests
import psutil
import subprocess
from kuro_backend.config import settings

logger = logging.getLogger(__name__)

# Disable SSL warnings for self-signed Proxmox certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Proxmox API Helper (Proven v1 approach using direct HTTP requests) ---
def _get_proxmox_headers():
    """Returns Authorization headers for Proxmox API requests."""
    token_id = settings.PVE_TOKEN_ID
    token_secret = settings.PVE_TOKEN_SECRET
    return {"Authorization": f"PVEAPIToken={token_id}={token_secret}"}


def get_system_status():
    """Mendapatkan status real-time CPU, RAM, Disk, dan Uptime dari server tempat Kuro berjalan.
    
    Optimized for low-RAM environments (non-blocking CPU check).
    """
    try:
        # Non-blocking CPU check (interval=0 returns since last call)
        cpu_usage = psutil.cpu_percent(interval=0)
        ram = psutil.virtual_memory()
        ram_usage = f"{ram.used / (1024**3):.2f}GB / {ram.total / (1024**3):.2f}GB ({ram.percent}%)"
        disk = psutil.disk_usage('/home/kuro/')
        disk_usage = f"{disk.used / (1024**3):.2f}GB / {disk.total / (1024**3):.2f}GB ({disk.percent}%)"
        uptime = subprocess.check_output(['uptime', '-p'], timeout=5).decode('utf-8').strip()

        return f"""Kuro System Health Report:
- CPU Usage: {cpu_usage}%
- RAM Usage: {ram_usage}
- Disk Space (/home/kuro/): {disk_usage}
- System Uptime: {uptime}"""
    except subprocess.TimeoutExpired:
        return "Kuro System Health Report:\n- Uptime: Unable to retrieve (timeout)"
    except Exception as e:
        logger.exception(f"Error in get_system_status: {e}")
        return f"Error retrieving system status: {e}"


def check_proxmox_infrastructure():
    """Mengambil status real-time VM dan Container dari server Proxmox Master.
    
    Uses direct HTTP requests (proven v1 approach) instead of proxmoxer library.
    """
    host = settings.PVE_HOST
    headers = _get_proxmox_headers()

    try:
        # Use cluster/resources endpoint (proven v1 approach)
        url = f"https://{host}:8006/api2/json/cluster/resources"
        resp = requests.get(url, headers=headers, verify=False, timeout=10)

        if resp.status_code != 200:
            return f"Error: Proxmox API returned status {resp.status_code}. Response: {resp.text}"

        data = resp.json().get('data', [])
        report = ["Proxmox Infrastructure Audit:"]
        warning_issued = False

        # Group by node for cleaner output
        nodes = {}
        for item in data:
            if item['type'] in ['qemu', 'lxc']:
                node = item.get('node', 'unknown')
                if node not in nodes:
                    nodes[node] = []
                nodes[node].append(item)

        for node_name, items in nodes.items():
            report.append(f"\nNode: {node_name}")
            for item in items:
                item_type = item['type'].upper()
                vmid = item.get('vmid', 'unknown')
                name = item.get('name', 'unnamed')
                status = item.get('status', 'unknown')
                report.append(f"  - {item_type} {vmid} ({name}): {status}")
                if status != 'running':
                    report.append(f"    -> WARNING: {item_type} is not running!")
                    warning_issued = True

        if not warning_issued:
            report.append("\nAll systems are running as expected.")

        return "\n".join(report)

    except requests.exceptions.Timeout:
        return f"Error: Connection to Proxmox ({host}:8006) timed out. Please check network connectivity."
    except requests.exceptions.ConnectionError as e:
        return f"Error: Cannot connect to Proxmox ({host}:8006). Detail: {e}"
    except Exception as e:
        logger.exception(f"Error connecting to Proxmox for audit: {e}")
        return f"Error connecting to Proxmox for audit: {e}"


def process_video(video_path: str):
    """Processes a video file using moviepy with RAM safeguards.
    
    - Checks file size before loading (max 100MB to prevent OOM)
    - Properly closes clip to free memory
    """
    MAX_VIDEO_SIZE_MB = 100

    try:
        if not os.path.exists(video_path):
            return f"Error: Video file not found: {video_path}"

        file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
        if file_size_mb > MAX_VIDEO_SIZE_MB:
            return f"Error: Video file too large ({file_size_mb:.1f}MB). Maximum allowed: {MAX_VIDEO_SIZE_MB}MB. This limit protects the 4GB RAM environment."

        # Lazy import to avoid loading moviepy into memory unless needed
        import moviepy as mp
        clip = None
        try:
            clip = mp.VideoFileClip(video_path)
            duration = clip.duration
            return f"Video duration: {duration:.2f} seconds."
        finally:
            # Ensure clip is properly closed to free memory
            if clip is not None:
                clip.close()
                del clip

    except ImportError:
        return "Error: moviepy library not installed. Run: pip install moviepy"
    except Exception as e:
        logger.exception(f"Error processing video: {e}")
        return f"Error processing video: {e}"
