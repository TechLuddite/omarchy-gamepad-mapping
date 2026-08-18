import QtQuick
import Quickshell.Io

// Headless half of the plugin: owns the controller-control daemon.
//
// The daemon is a small pure-stdlib Python process that reads the pad from
// /dev/input and runs the bound actions. It speaks one JSON object per line on
// stdout, which is what everything below is parsing. Keeping the reader here
// -- rather than in the bar widget -- means the pad keeps working whether or
// not the widget is on the bar, and there is only ever one reader.
Item {
  id: root

  // Injected by omarchy-shell's service loader.
  property var shell: null
  property var manifest: null

  readonly property string pluginDir: Qt.resolvedUrl(".").toString().replace(/^file:\/\//, "")
  readonly property string cli: pluginDir + "bin/controller-control"

  // ---- live state, read by BarWidget.qml and Panel.qml -------------------

  property bool running: false
  property bool connected: false
  property string deviceName: ""
  property string devicePath: ""
  property bool exclusive: false
  property int bindingCount: 0
  property int daemonPid: 0
  property string lastError: ""

  // Buttons physically held right now, as canonical tokens.
  property var heldButtons: []
  // Most recent binding that fired, for the widget's flash and the panel log.
  property string lastFired: ""
  property string lastFiredLabel: ""
  property real lastFiredAt: 0

  // ---- combo capture ("press the combo you want to bind") ---------------

  property bool capturing: false
  property var capturedCombo: []
  property var _capturePeak: []

  signal comboCaptured(var combo)
  signal fired(string label, string description)

  function startCapture() {
    root._capturePeak = []
    root.capturedCombo = []
    root.capturing = true
  }

  function cancelCapture() {
    root.capturing = false
    root._capturePeak = []
  }

  function _captureButton(button, pressed, held) {
    if (!root.capturing) return
    if (pressed) {
      // Track the largest set held at once, so "L then R" records "L + R".
      if (held.length >= root._capturePeak.length) root._capturePeak = held.slice()
      return
    }
    if (held.length === 0 && root._capturePeak.length > 0) {
      var combo = root._capturePeak.slice().sort()
      root.capturing = false
      root.capturedCombo = combo
      root._capturePeak = []
      root.comboCaptured(combo)
    }
  }

  // ---- daemon control ---------------------------------------------------

  function start() {
    if (daemon.running) return
    root.lastError = ""
    daemon.running = true
  }

  function stop() {
    daemon.running = false
  }

  function restart() {
    stop()
    restartTimer.restart()
  }

  // The daemon re-reads its config on SIGHUP, which is cheaper and less
  // disruptive than bouncing the process (no re-grab of the pad).
  function reload() {
    if (root.daemonPid > 0) {
      reloadProc.command = ["kill", "-HUP", String(root.daemonPid)]
      reloadProc.running = true
    } else {
      restart()
    }
  }

  function _handle(line) {
    var event
    try {
      event = JSON.parse(line)
    } catch (e) {
      return
    }
    if (!event || !event.event) return

    switch (event.event) {
    case "started":
      root.running = true
      root.daemonPid = Number(event.pid) || 0
      break
    case "state":
      root.connected = event.connected === true
      root.bindingCount = Number(event.bindings) || 0
      root.exclusive = event.exclusive === true
      if (Array.isArray(event.devices) && event.devices.length > 0) {
        root.deviceName = String(event.devices[0].name || "")
        root.devicePath = String(event.devices[0].path || "")
      } else {
        root.deviceName = ""
        root.devicePath = ""
      }
      break
    case "connected":
      root.connected = true
      root.deviceName = String(event.name || "")
      root.devicePath = String(event.path || "")
      break
    case "disconnected":
      root.connected = false
      root.deviceName = ""
      root.devicePath = ""
      root.heldButtons = []
      break
    case "button":
      var held = Array.isArray(event.held) ? event.held : []
      root.heldButtons = held
      root._captureButton(String(event.button || ""), event.pressed === true, held)
      break
    case "fire":
      root.lastFired = String(event.label || "")
      root.lastFiredLabel = String(event.description || event.action || "")
      root.lastFiredAt = Date.now()
      root.fired(root.lastFired, root.lastFiredLabel)
      break
    case "reloaded":
      root.bindingCount = Number(event.bindings) || 0
      break
    case "error":
      root.lastError = String(event.message || "")
      break
    case "stopped":
      root.running = false
      break
    }
  }

  Process {
    id: daemon
    command: [root.cli, "daemon"]
    running: false

    stdout: SplitParser {
      onRead: function (line) { root._handle(line) }
    }
    stderr: SplitParser {
      onRead: function (line) {
        if (line && line.trim() !== "") root.lastError = line
      }
    }

    onExited: function (exitCode, exitStatus) {
      root.running = false
      root.connected = false
      root.daemonPid = 0
      root.heldButtons = []
      if (exitCode !== 0 && root.lastError === "")
        root.lastError = "daemon exited with code " + exitCode
      // Come back up on its own; a crashed daemon means a dead controller.
      restartTimer.restart()
    }
  }

  Process { id: reloadProc }

  Timer {
    id: restartTimer
    interval: 3000
    repeat: false
    onTriggered: root.start()
  }

  IpcHandler {
    target: "controller"

    function status(): string {
      return JSON.stringify({
        running: root.running,
        connected: root.connected,
        device: root.deviceName,
        bindings: root.bindingCount,
        exclusive: root.exclusive,
        held: root.heldButtons,
        error: root.lastError
      })
    }

    function reload(): string {
      root.reload()
      return "ok"
    }

    function restart(): string {
      root.restart()
      return "ok"
    }
  }

  Component.onCompleted: start()
  Component.onDestruction: stop()
}
