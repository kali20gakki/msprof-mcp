"""Connection manager for persistent TraceProcessor connections."""

import threading
import logging
import json
from typing import Callable, Any, Dict, Optional
from perfetto.trace_processor import TraceProcessor, TraceProcessorConfig

from .trace_processor_shell import resolve_trace_processor_shell_path


logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages persistent TraceProcessor connections with reconnection support."""
    
    def __init__(self):
        self._current_trace_path: Optional[str] = None
        self._current_connection: Optional[TraceProcessor] = None
        self._lock = threading.Lock()  # Thread safety
        
    def get_connection(self, trace_path: str) -> TraceProcessor:
        """Get or create connection for trace_path with automatic reconnection.
        
        Args:
            trace_path: Path to the Perfetto trace file
            
        Returns:
            TraceProcessor: Active connection to the trace
            
        Raises:
            FileNotFoundError: If trace file doesn't exist
            ConnectionError: If connection fails
        """
        with self._lock:
            # If different path, close existing and open new
            if self._current_trace_path != trace_path:
                self._close_current_unsafe()
                self._current_trace_path = trace_path
                self._current_connection = self._create_connection(trace_path)
                
            # If same path but no connection, create new one
            elif self._current_connection is None:
                self._current_connection = self._create_connection(trace_path)
                
            # Test connection health before returning
            if not self._is_connection_healthy():
                logger.warning(f"Connection to {trace_path} appears unhealthy, reconnecting")
                self._current_connection = self._reconnect_unsafe(trace_path)
                
            return self._current_connection
    
    def _create_connection(self, trace_path: str) -> TraceProcessor:
        """Create a new TraceProcessor connection.
        
        Args:
            trace_path: Path to the trace file
            
        Returns:
            TraceProcessor: New connection
            
        Raises:
            FileNotFoundError: If trace file doesn't exist
            ConnectionError: If connection fails
        """
        try:
            shell_path = resolve_trace_processor_shell_path()
        except FileNotFoundError as e:
            logger.error(f"Configured trace processor shell is missing: {e}")
            raise ConnectionError(str(e))

        try:
            tp = TraceProcessor(
                trace=trace_path,
                config=TraceProcessorConfig(bin_path=shell_path),
            )
            return tp
        except FileNotFoundError as e:
            logger.error(f"Trace file not found: {trace_path}")
            raise FileNotFoundError(
                f"Failed to open the trace file. Please double-check the trace_path "
                f"you supplied. Underlying error: {e}"
            )
        except Exception as e:
            logger.error(f"Failed to connect to trace: {trace_path}, error: {e}")
            raise ConnectionError(f"Could not connect to trace processor: {e}")
    
    def _is_connection_healthy(self) -> bool:
        """Check if the current connection is healthy.
        
        Returns:
            bool: True if connection is healthy, False otherwise
        """
        if self._current_connection is None:
            return False
            
        try:
            # Try a simple query to test connection health
            qr_it = self._current_connection.query('SELECT 1 as test_query LIMIT 1;')
            # Consume the iterator to ensure query executes
            list(qr_it)
            return True
        except Exception as e:
            logger.warning(f"Connection health check failed: {e}")
            return False
    
    def _reconnect(self, trace_path: str) -> TraceProcessor:
        """Reconnect to trace file after connection failure.
        
        Args:
            trace_path: Path to the trace file
            
        Returns:
            TraceProcessor: New connection
            
        Raises:
            ConnectionError: If reconnection fails
        """
        with self._lock:
            return self._reconnect_unsafe(trace_path)
    
    def _reconnect_unsafe(self, trace_path: str) -> TraceProcessor:
        """Reconnect without acquiring lock (internal use only).
        
        Args:
            trace_path: Path to the trace file
            
        Returns:
            TraceProcessor: New connection
        """
        # Close existing connection
        self._close_current_unsafe()
        
        # Create new connection
        try:
            self._current_connection = self._create_connection(trace_path)
            self._current_trace_path = trace_path
            return self._current_connection
        except Exception as e:
            logger.error(f"Reconnection failed for {trace_path}: {e}")
            raise ConnectionError(f"Reconnection failed: {e}")
    
    def close_current(self):
        """Close the current connection if it exists."""
        with self._lock:
            self._close_current_unsafe()
    
    def _close_current_unsafe(self):
        """Close current connection without acquiring lock (internal use only)."""
        if self._current_connection is not None:
            try:
                self._current_connection.close()
            except Exception as e:
                logger.warning(f"Error closing connection: {e}")
            finally:
                self._current_connection = None
                self._current_trace_path = None
    
    def cleanup(self):
        """Cleanup method called by MCP server shutdown lifecycle."""
        self.close_current()
    
    def get_current_trace_path(self) -> Optional[str]:
        """Get the currently connected trace path.
        
        Returns:
            Optional[str]: Current trace path or None if no connection
        """
        with self._lock:
            return self._current_trace_path
    
    def is_connected(self) -> bool:
        """Check if there's an active connection.
        
        Returns:
            bool: True if connected, False otherwise
        """
        with self._lock:
            return self._current_connection is not None

class ToolError(Exception):
    """Custom exception carrying a structured error code and message."""

    def __init__(self, code: str, message: str, details: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class BaseTool:
    """Base class for all Perfetto tools with connection management and formatting."""

    def __init__(self, connection_manager: ConnectionManager):
        """Initialize the tool with a connection manager.

        Args:
            connection_manager: Shared connection manager instance
        """
        self.connection_manager = connection_manager

    def execute_with_connection(self, trace_path: str, operation: Callable) -> Any:
        """Execute operation with managed connection and auto-reconnection.

        Args:
            trace_path: Path to the trace file
            operation: Function that takes a TraceProcessor and returns a result

        Returns:
            Any: Result from the operation

        Raises:
            FileNotFoundError: If trace file doesn't exist
            ConnectionError: If connection fails
            Exception: Any other errors from the operation
        """
        try:
            tp = self.connection_manager.get_connection(trace_path)
            return operation(tp)
        except (ConnectionError, Exception) as e:
            # Check if this is a connection-related error that might benefit from reconnection
            if self._should_retry_on_error(e):
                try:
                    tp = self.connection_manager._reconnect(trace_path)
                    return operation(tp)
                except Exception as reconnect_error:
                    logger.error(f"Reconnection attempt failed: {reconnect_error}")
                    # Raise the original error if reconnection fails
                    raise e
            else:
                # Don't retry for errors like FileNotFoundError
                raise e

    def _should_retry_on_error(self, error: Exception) -> bool:
        """Determine if an error should trigger a reconnection attempt.

        Args:
            error: The exception that occurred

        Returns:
            bool: True if reconnection should be attempted
        """
        # Don't retry for file not found errors
        if isinstance(error, FileNotFoundError):
            return False

        # Retry for connection errors or other exceptions that might be connection-related
        if isinstance(error, ConnectionError):
            return True

        # Check if error message suggests connection issues
        error_str = str(error).lower()
        connection_indicators = [
            'connection', 'broken pipe', 'socket', 'network', 'timeout',
            'disconnected', 'closed', 'reset', 'refused'
        ]

        for indicator in connection_indicators:
            if indicator in error_str:
                return True

        return False

    # -------------------------
    # Unified response helpers
    # -------------------------
    def _make_envelope(
        self,
        *,
        trace_path: Optional[str],
        process_name: Optional[str],
        success: bool,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create the standard response envelope."""
        return {
            "processName": process_name or "not-specified",
            "tracePath": trace_path,
            "success": success,
            "error": error,
            "result": result or {},
        }

    def _error(self, code: str, message: str, details: Optional[str] = None) -> Dict[str, Any]:
        """Create a standardized error object."""
        err: Dict[str, Any] = {"code": code, "message": message}
        if details:
            err["details"] = details
        return err

    def run_formatted(
        self,
        trace_path: str,
        process_name: Optional[str],
        op: Callable[[Any], Dict[str, Any]],  # (tp) -> Dict[str, Any] (result payload)
    ) -> str:
        """Run an operation with connection management and return a JSON envelope string."""
        try:
            def wrapped(tp):
                result = op(tp)
                return self._make_envelope(
                    trace_path=trace_path,
                    process_name=process_name,
                    success=True,
                    result=result,
                )

            envelope = self.execute_with_connection(trace_path, wrapped)
        except ToolError as te:
            envelope = self._make_envelope(
                trace_path=trace_path,
                process_name=process_name,
                success=False,
                error=self._error(te.code, te.message, te.details),
            )
        except FileNotFoundError as fnf:
            envelope = self._make_envelope(
                trace_path=trace_path,
                process_name=process_name,
                success=False,
                error=self._error("FILE_NOT_FOUND", "Trace file not found", str(fnf)),
            )
        except ConnectionError as ce:
            envelope = self._make_envelope(
                trace_path=trace_path,
                process_name=process_name,
                success=False,
                error=self._error("CONNECTION_FAILED", "Could not connect to trace processor", str(ce)),
            )
        except Exception as e:
            envelope = self._make_envelope(
                trace_path=trace_path,
                process_name=process_name,
                success=False,
                error=self._error("INTERNAL_ERROR", str(e)),
            )

        return json.dumps(envelope, indent=2)
