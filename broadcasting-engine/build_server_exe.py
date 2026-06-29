"""
Build a standalone Broadcasting Engine server executable (no Python needed).

Produces ONE program that runs either server role via a flag:
    dist_server/StreamEngineServer/StreamEngineServer.exe --role origin     (Server A)
    dist_server/StreamEngineServer/StreamEngineServer.exe --role edge --origin http://A:5000  (Server B)

Two double-click launchers are generated next to it (Start-ServerA / Start-ServerB).

Run:  python build_server_exe.py
"""
import os
import shutil
import PyInstaller.__main__


NAME = 'StreamEngineServer'


def locate_ffmpeg():
    """Find an ffmpeg.exe to bundle (optional; only used for MP4 downloads)."""
    candidates = [
        os.path.join('ffmpeg', 'ffmpeg.exe'),
        os.path.join('ffmpeg', 'bin', 'ffmpeg.exe'),
        os.path.join('..', 'screen-broadcast-client', 'ffmpeg', 'ffmpeg.exe'),
        r'C:\ffmpeg\bin\ffmpeg.exe',
    ]
    w = shutil.which('ffmpeg')
    if w:
        candidates.append(w)
    for c in candidates:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    return None


def build():
    print('=' * 60)
    print('Building', NAME)
    print('=' * 60)

    args = [
        'server_app.py',
        f'--name={NAME}',
        '--onedir',          # folder build: workers re-launch the exe with NO re-extraction
        '--console',         # it's a server: show logs, allow Ctrl+C
        '--noconfirm',
        '--clean',
        '--distpath=./dist_server',
        '--workpath=./build_server',
        # These are imported lazily inside server_app by role; pin them explicitly.
        '--hidden-import=app',
        '--hidden-import=manager',
        '--hidden-import=single_engine',
        '--hidden-import=relay',
        '--hidden-import=config',
        '--hidden-import=flask',
        '--hidden-import=flask_cors',
        '--hidden-import=requests',
        '--hidden-import=dotenv',
        '--hidden-import=waitress',
    ]

    ffmpeg_bin = locate_ffmpeg()
    if ffmpeg_bin:
        print('Bundling ffmpeg from:', ffmpeg_bin)
        args.append(f'--add-binary={ffmpeg_bin}{os.pathsep}ffmpeg')
    else:
        print('NOTE: ffmpeg not found -> MP4 "download recording" will fall back to a')
        print('      concatenated .ts file. Put ffmpeg.exe in ./ffmpeg to bundle it.')

    print('\nBuilding (this takes a minute or two)...\n')
    PyInstaller.__main__.run(args)

    _write_launchers()

    print('\n' + '=' * 60)
    print('Build complete!  ->  dist_server/' + NAME + '/')
    print('=' * 60)
    print('Server A:  run  Start-ServerA.bat   (or  {0}.exe --role origin)'.format(NAME))
    print('Server B:  edit Start-ServerB.bat to set Server A\'s address, then run it')


def _write_launchers():
    """Drop double-click .bat launchers + a README next to the built program."""
    out = os.path.join('dist_server')
    exe_rel = os.path.join(NAME, NAME + '.exe')

    with open(os.path.join(out, 'Start-ServerA.bat'), 'w') as f:
        f.write(
            '@echo off\r\n'
            'rem ===== Server A (origin): clients upload here =====\r\n'
            f'"%~dp0{exe_rel}" --role origin --port 5000\r\n'
            'pause\r\n'
        )

    with open(os.path.join(out, 'Start-ServerB.bat'), 'w') as f:
        f.write(
            '@echo off\r\n'
            'rem ===== Server B (edge): mirrors Server A and serves viewers =====\r\n'
            'rem  EDIT the address below to point at YOUR Server A:\r\n'
            'set ORIGIN=http://CHANGE-ME-SERVER-A-IP:5000\r\n'
            f'"%~dp0{exe_rel}" --role edge --port 5000 --origin %ORIGIN%\r\n'
            'pause\r\n'
        )

    with open(os.path.join(out, 'README.txt'), 'w') as f:
        f.write(
            'Broadcasting Engine - standalone servers\r\n'
            '========================================\r\n\r\n'
            'No Python needed. Copy the StreamEngineServer folder to each server.\r\n\r\n'
            'SERVER A (origin / repository):\r\n'
            '  Double-click Start-ServerA.bat\r\n'
            '  (or run:  StreamEngineServer\\StreamEngineServer.exe --role origin)\r\n'
            '  Screen-broadcast clients point at  http://<server-A-ip>:5000\r\n\r\n'
            'SERVER B (edge / broadcaster):\r\n'
            '  1) Edit Start-ServerB.bat, set ORIGIN to your Server A address.\r\n'
            '  2) Double-click Start-ServerB.bat\r\n'
            '     (or run: StreamEngineServer\\StreamEngineServer.exe --role edge \\\r\n'
            '              --origin http://<server-A-ip>:5000)\r\n'
            '  Viewers point at  http://<server-B-ip>:5000\r\n'
            '  Run as many Server B machines as you like (all with the same origin).\r\n\r\n'
            'Open TCP 5000 in the firewall on each server.\r\n'
            'Recordings are stored in a transcode_temp folder next to the exe.\r\n'
        )


if __name__ == '__main__':
    build()
