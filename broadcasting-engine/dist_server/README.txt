Broadcasting Engine - standalone servers
========================================

No Python needed. Copy the StreamEngineServer folder to each server.

SERVER A (origin / repository):
  Double-click Start-ServerA.bat
  (or run:  StreamEngineServer\StreamEngineServer.exe --role origin)
  Screen-broadcast clients point at  http://<server-A-ip>:5000

SERVER B (edge / broadcaster):
  1) Edit Start-ServerB.bat, set ORIGIN to your Server A address.
  2) Double-click Start-ServerB.bat
     (or run: StreamEngineServer\StreamEngineServer.exe --role edge \
              --origin http://<server-A-ip>:5000)
  Viewers point at  http://<server-B-ip>:5000
  Run as many Server B machines as you like (all with the same origin).

Open TCP 5000 in the firewall on each server.
Recordings are stored in a transcode_temp folder next to the exe.
