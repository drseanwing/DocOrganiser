"""
Run the Document Organizer v2 API server.

Usage:
    python run_server.py [--host HOST] [--port PORT] [--reload]
"""

import argparse
import uvicorn


def main():
    """Run the FastAPI server."""
    parser = argparse.ArgumentParser(description="Document Organizer v2 API Server")
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind to (default: 8000)"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development"
    )

    args = parser.parse_args()

    uvicorn.run(
        "src.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info"
    )


if __name__ == "__main__":
    main()
