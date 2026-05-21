"""Backward-compatible entrypoint for web UI module."""

from ticket_modules.web.ui_app import app


if __name__ == "__main__":
    print("TicketOrchestrator UI -> http://localhost:5000")
    app.run(debug=True, port=5000, threaded=True)
