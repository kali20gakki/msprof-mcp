"""
MSProf Analyze Command Tool for performance bottleneck analysis.
"""

import json
import logging
import os
import re
import subprocess
from typing import Literal

logger = logging.getLogger(__name__)
TIMEOUT_SECONDS = 3000
LOG_LINE_PATTERN = re.compile(
    r"^\[(?P<timestamp>[^\]]+)\]\[(?P<level>[A-Z]+)\]\s*(?P<message>.*)$"
)
PROGRESS_PREFIXES = (
    "Building dataset for timeline analysis:",
    "Scanning timeline for affinity apis:",
)


def _is_progress_line(line: str) -> bool:
    stripped = line.strip()
    return any(stripped.startswith(prefix) for prefix in PROGRESS_PREFIXES)


def _extract_json_message(message: str) -> str | None:
    candidate = message.strip()
    if not candidate or candidate[0] not in "{[":
        return None

    try:
        json.loads(candidate)
    except json.JSONDecodeError:
        return None

    return candidate


def _sanitize_success_output(stdout: str, stderr: str) -> tuple[str, str]:
    cleaned_stdout = stdout.strip()
    stderr_lines: list[str] = []
    extracted_json: str | None = None

    for raw_line in stderr.splitlines():
        if not raw_line.strip() or _is_progress_line(raw_line):
            continue

        match = LOG_LINE_PATTERN.match(raw_line.strip())
        if not match:
            stderr_lines.append(raw_line.strip())
            continue

        level = match.group("level")
        message = match.group("message").strip()

        if level == "INFO":
            json_message = _extract_json_message(message)
            if json_message:
                extracted_json = json_message
            continue

        stderr_lines.append(raw_line.strip())

    if not cleaned_stdout and extracted_json:
        cleaned_stdout = extracted_json

    return cleaned_stdout, "\n".join(stderr_lines)


class MsProfAnalyzer:
    """
    Wrapper for msprof-analyze advisor command.
    
    This tool executes msprof-analyze and returns the analysis result while
    suppressing noisy progress logs emitted to stderr.
    """
    
    def msprof_analyze_advisor(
        self,
        profiler_data_dir: str,
        mode: Literal["all", "computation", "schedule"] = "all",
    ) -> str:
        """
        Execute msprof-analyze advisor command and return analysis output.
        
        SCOPE:
        - Executes `msprof-analyze advisor` command on Ascend Profiler data.
        - Extracts the useful analysis result from command output.
        
        CAPABILITIES:
        - Comprehensive performance analysis (computation + schedule bottlenecks)
        - Suppresses noisy INFO/progress logs on successful execution
        - Detailed error reporting with context
        
        PARAMETERS:
        - profiler_data_dir: Absolute path to the profiling data directory
        - mode: Analysis mode (default: "all")
            * "all": Recommended. Comprehensive analysis (computation + schedule).
                     DO NOT call "computation" or "schedule" separately if using "all".
            * "computation": Analyze only calculation bottlenecks.
            * "schedule": Analyze only scheduling bottlenecks.
        
        OUTPUT:
        Returns JSON string with:
        - execution_info: Command execution metadata (command, directory, mode, status)
        - stdout: Analysis result content
        - stderr: Warnings/errors only for successful runs
        - error: Error information (if execution failed)
        
        USAGE EXAMPLES:
        - "分析 /path/to/data 目录下的性能数据，找出主要瓶颈"
        - "对 /path/to/profiler/data 执行全面的性能分析"
        - "检查 /path/to/data 的计算瓶颈"
        """
        # Validate input directory
        if not profiler_data_dir:
            return json.dumps({
                "error": "INVALID_PARAMETER",
                "message": "profiler_data_dir cannot be empty",
                "execution_info": {
                    "directory": profiler_data_dir,
                    "mode": mode,
                    "status": "failed"
                }
            }, indent=2)
        
        if not os.path.exists(profiler_data_dir):
            return json.dumps({
                "error": "DIRECTORY_NOT_FOUND",
                "message": f"Profiler data directory does not exist: {profiler_data_dir}",
                "execution_info": {
                    "directory": profiler_data_dir,
                    "mode": mode,
                    "status": "failed"
                }
            }, indent=2)
        
        if not os.path.isdir(profiler_data_dir):
            return json.dumps({
                "error": "NOT_A_DIRECTORY",
                "message": f"Path is not a directory: {profiler_data_dir}",
                "execution_info": {
                    "directory": profiler_data_dir,
                    "mode": mode,
                    "status": "failed"
                }
            }, indent=2)
        
        # Construct command
        cmd = ["msprof-analyze", "advisor", mode, "-d", profiler_data_dir, "--stdout"]
        
        try:
            # Execute command
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=TIMEOUT_SECONDS
            )

            cleaned_stdout, cleaned_stderr = _sanitize_success_output(
                result.stdout,
                result.stderr,
            )
            
            response = {
                "execution_info": {
                    "command": " ".join(cmd),
                    "directory": profiler_data_dir,
                    "mode": mode,
                    "status": "success",
                    "return_code": result.returncode
                },
                "stdout": cleaned_stdout,
                "stderr": cleaned_stderr
            }
            
            return json.dumps(response, indent=2, ensure_ascii=False)
            
        except subprocess.TimeoutExpired:
            logger.error(
                f"Command timeout after {TIMEOUT_SECONDS} seconds: {' '.join(cmd)}"
            )
            return json.dumps({
                "error": "EXECUTION_TIMEOUT",
                "message": (
                    f"msprof-analyze command timed out after {TIMEOUT_SECONDS} seconds"
                ),
                "execution_info": {
                    "command": " ".join(cmd),
                    "directory": profiler_data_dir,
                    "mode": mode,
                    "status": "timeout"
                }
            }, indent=2)
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed with return code {e.returncode}: {e.stderr}")
            return json.dumps({
                "error": "EXECUTION_FAILED",
                "message": f"msprof-analyze command failed with return code {e.returncode}",
                "execution_info": {
                    "command": " ".join(cmd),
                    "directory": profiler_data_dir,
                    "mode": mode,
                    "status": "failed",
                    "return_code": e.returncode
                },
                "stdout": e.stdout if e.stdout else "",
                "stderr": e.stderr if e.stderr else ""
            }, indent=2)
            
        except FileNotFoundError:
            logger.error("msprof-analyze command not found in PATH")
            return json.dumps({
                "error": "COMMAND_NOT_FOUND",
                "message": "msprof-analyze command not found. Please ensure MSProf is installed and in your PATH.",
                "execution_info": {
                    "command": " ".join(cmd),
                    "directory": profiler_data_dir,
                    "mode": mode,
                    "status": "failed"
                },
                "troubleshooting": [
                    "Check if MSProf is installed: which msprof-analyze",
                    "Verify PATH environment variable includes MSProf bin directory",
                    "Install MSProf if not present"
                ]
            }, indent=2)
            
        except Exception as e:
            logger.error(f"Unexpected error executing msprof-analyze: {e}", exc_info=True)
            return json.dumps({
                "error": "UNEXPECTED_ERROR",
                "message": f"Unexpected error: {str(e)}",
                "execution_info": {
                    "command": " ".join(cmd),
                    "directory": profiler_data_dir,
                    "mode": mode,
                    "status": "failed"
                }
            }, indent=2)


# Create singleton instance
_analyzer = MsProfAnalyzer()


def msprof_analyze_advisor(
    profiler_data_dir: str,
    mode: Literal["all", "computation", "schedule"] = "all",
) -> str:
    """
    Execute msprof-analyze advisor command and return analysis output.
    
    SCOPE:
    - Executes `msprof-analyze advisor` command on Ascend Profiler data.
    - Extracts the useful analysis result from command output.
    
    CAPABILITIES:
    - Comprehensive performance analysis (computation + schedule bottlenecks)
    - Suppresses noisy INFO/progress logs on successful execution
    - Detailed error reporting with context
    
    PARAMETERS:
    - profiler_data_dir: Absolute path to the profiling data directory
    - mode: Analysis mode (default: "all")
        * "all": Recommended. Comprehensive analysis (computation + schedule).
                 DO NOT call "computation" or "schedule" separately if using "all".
        * "computation": Analyze only calculation bottlenecks.
        * "schedule": Analyze only scheduling bottlenecks.
    
    OUTPUT:
    Returns JSON string with:
    - execution_info: Command execution metadata (command, directory, mode, status)
    - stdout: Analysis result content
    - stderr: Warnings/errors only for successful runs
    - error: Error information (if execution failed)
    
    USAGE EXAMPLES:
    - "分析 /path/to/data 目录下的性能数据，找出主要瓶颈"
    - "对 /path/to/profiler/data 执行全面的性能分析"
    - "检查 /path/to/data 的计算瓶颈"
    """
    return _analyzer.msprof_analyze_advisor(profiler_data_dir, mode)


if __name__ == "__main__":
    res = msprof_analyze_advisor("/Users/weizhang/Downloads/kv_cache_type_page_seqlen_1024_bs_1_profile_count_0", "all")
    print(res)
