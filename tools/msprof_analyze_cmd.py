
import os
import subprocess
from typing import Literal

def msprof_analyze_advisor(
    profiler_data_dir: str,
    mode: Literal["all", "computation", "schedule"] = "all",
) -> str:
    """
    Analyze performance bottlenecks using msprof-analyze.

    Args:
        profiler_data_dir: Path to the profiling data directory
        mode: Analysis mode. Defaults to "all".
            - "all": Recommended. Performs a comprehensive analysis including "computation" and "schedule".
                     If you choose "all", DO NOT call "computation" or "schedule" separately as they are redundant.
            - "computation": Analyze only calculation bottlenecks. Use this only if you specifically need just computation data.
            - "schedule": Analyze only scheduling bottlenecks. Use this only if you specifically need just schedule data.
    """
    if not os.path.exists(profiler_data_dir):
        return f"Error: Profiler data directory '{profiler_data_dir}' does not exist."

    # Construct the command based on user examples:
    # msprof-analyze advisor all -d <dir>
    cmd = ["msprof-analyze", "advisor", mode, "-d", profiler_data_dir]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"Error running msprof-analyze: {e.stderr}"
    except FileNotFoundError:
        return "Error: 'msprof-analyze' command not found. Please ensure it is installed and in your PATH."
