# camera package — abstraction de source vidéo pour GREEN
from .provider   import CameraProvider, CameraInfo
from .state      import camera_state
from .esp32      import ESP32CameraProvider
from .discovery  import discover_esp32

__all__ = [
    "CameraProvider",
    "CameraInfo",
    "camera_state",
    "ESP32CameraProvider",
    "discover_esp32",
]
