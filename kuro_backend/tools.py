from proxmoxer import ProxmoxAPI
from kuro_backend.config import settings
import moviepy as mp

def get_proxmox_status():
    """Fetches the status from the Proxmox server."""
    try:
        proxmox = ProxmoxAPI(settings.PVE_HOST, user=settings.PVE_TOKEN_ID, token=settings.PVE_TOKEN_SECRET, verify_ssl=False)
        return proxmox.nodes.get()
    except Exception as e:
        return f"Error connecting to Proxmox: {e}"

def process_video(video_path: str):
    """Processes a video file using moviepy."""
    try:
        clip = mp.VideoFileClip(video_path)
        # Example processing: return video duration
        return f"Video duration: {clip.duration} seconds."
    except Exception as e:
        return f"Error processing video: {e}"
