"""
Web Viewer (Part 3) - standalone viewer web app.

Serves the live dashboard and the single-stream player pages. It holds NO video
itself: every API/HLS request goes to the Broadcasting Engine (Part 2), whose
base URL is injected into the pages as `window.ENGINE_URL`. The engine has CORS
enabled, so the browser can fetch the playlist/segments cross-origin.

Configure the engine location with the ENGINE_URL env var (see .env.example).
"""
from flask import Flask, render_template, redirect

from config import Config


def create_app():
    app = Flask(__name__, template_folder='templates')
    app.config.from_object(Config)

    engine_url = Config.ENGINE_URL.rstrip('/')

    @app.route('/')
    def index():
        return redirect('/live')

    @app.route('/live')
    def live_dashboard():
        """Live streaming dashboard (lists all broadcasts)."""
        return render_template('streaming_dashboard.html', engine_url=engine_url)

    @app.route('/viewer/<stream_id>')
    def stream_viewer(stream_id):
        """Full-page player for one stream (live or replay)."""
        return render_template('stream_viewer.html',
                               stream_id=stream_id, engine_url=engine_url)

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG, threaded=True)
