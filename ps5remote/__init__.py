"""PS5 phone remote."""
import warnings

# Video decoding (PyAV/FFmpeg) is deliberately not installed; pyremoteplay warns about it on import.
warnings.filterwarnings("ignore", message="av not installed")
