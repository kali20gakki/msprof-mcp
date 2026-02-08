"""
MSProf Analyze Command Tool for performance bottleneck analysis.
"""

import json
import logging
import os
import subprocess
from typing import Literal

logger = logging.getLogger(__name__)


class MsProfAnalyzer:
    """
    Wrapper for msprof-analyze advisor command.
    
    This tool executes msprof-analyze and returns the raw command output
    without any filtering or processing.
    """
    
    def msprof_analyze_advisor(
        self,
        profiler_data_dir: str,
        mode: Literal["all", "computation", "schedule"] = "all",
    ) -> str:
        """
        Execute msprof-analyze advisor command and return raw output.
        
        SCOPE:
        - Executes `msprof-analyze advisor` command on Ascend Profiler data.
        - Returns raw command output without any processing.
        
        CAPABILITIES:
        - Comprehensive performance analysis (computation + schedule bottlenecks)
        - Returns complete, unfiltered command output for LLM analysis
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
        - stdout: Complete stdout from the command (unfiltered)
        - stderr: Complete stderr from the command (if any)
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
        cmd = ["msprof-analyze", "advisor", mode, "-d", profiler_data_dir]
        
        try:
            # Execute command
            logger.info(f"Executing: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=300  # 5 minutes timeout
            )
            
            # Build response with raw output (no processing)
            response = {
                "execution_info": {
                    "command": " ".join(cmd),
                    "directory": profiler_data_dir,
                    "mode": mode,
                    "status": "success",
                    "return_code": result.returncode
                },
                "stdout": result.stdout,
                "stderr": result.stderr
            }
            
            return json.dumps(response, indent=2, ensure_ascii=False)
            
        except subprocess.TimeoutExpired:
            logger.error(f"Command timeout after 300 seconds: {' '.join(cmd)}")
            return json.dumps({
                "error": "EXECUTION_TIMEOUT",
                "message": "msprof-analyze command timed out after 300 seconds",
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
    Execute msprof-analyze advisor command and return raw output.
    
    SCOPE:
    - Executes `msprof-analyze advisor` command on Ascend Profiler data.
    - Returns raw command output without any processing.
    
    CAPABILITIES:
    - Comprehensive performance analysis (computation + schedule bottlenecks)
    - Returns complete, unfiltered command output for LLM analysis
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
    - stdout: Complete stdout from the command (unfiltered)
    - stderr: Complete stderr from the command (if any)
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