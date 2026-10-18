import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// Keep bar access as a popup; an ordinary window also supports touch keyboards
// without the popup's overlay layer intercepting taps outside the editor.
Panel {
  id: root
  moduleName: "co.klair.controller-control"
  ipcTarget: "co.klair.controller-control"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property var service: null
  readonly property var barIdentity: hostWidget || root
  readonly property Item form: editor
  readonly property bool windowOpened: editorWindow.visible

  function open() {
    root.controller.show()
    editorWindow.visible = false
  }

  function openWindow() {
    // A native close can leave the requested visibility true internally.
    if (!editorWindow.visible) editorWindow.visible = false
    editorWindow.visible = true
    root.controller.hide()
    Qt.callLater(function() { if (editorWindow.visible) editor.forceActiveFocus() })
  }

  function close() {
    root.controller.hide()
    editorWindow.visible = false
    cancelCaptureIfActive()
  }

  function cancelCaptureIfActive() {
    if (service) service.cancelCapture()
  }

  function ensureVisible(item) {
    var scroll = editorWindow.visible ? windowScroll : popupScroll
    if (!item || item === editor || item === editor.navigationItem || scroll.height <= 0) return
    var ancestor = item.parent
    while (ancestor && ancestor !== editor) ancestor = ancestor.parent
    if (ancestor !== editor) return
    var point = item.mapToItem(scroll.contentItem, 0, 0)
    var margin = Style.space(8)
    var top = point.y
    var bottom = top + item.height
    var offset = scroll.contentY
    if (top < offset + margin) offset = top - margin
    else if (bottom > offset + scroll.height - margin)
      offset = bottom - scroll.height + margin
    scroll.contentY = Math.max(0, Math.min(offset, scroll.contentHeight - scroll.height))
  }

  function revealFocus() {
    Qt.callLater(function() { root.ensureVisible(editor.focusScrollTarget) })
  }

  function closePopup() {
    root.controller.hide()
    if (!root.windowOpened) cancelCaptureIfActive()
  }

  function closeWindow() {
    editorWindow.visible = false
    if (!root.opened) cancelCaptureIfActive()
  }

  function toggle() { root.opened ? root.closePopup() : root.open() }

  // Also release capture when the bar coordinator closes the popup or the
  // compositor closes the window, rather than only through our Close button.
  onOpenedChanged: if (!opened && !windowOpened) cancelCaptureIfActive()
  Component.onDestruction: cancelCaptureIfActive()

  EditorContent {
    id: editor
    parent: editorWindow.visible ? windowScroll.contentItem : popupScroll.contentItem
    width: parent.width
    service: root.service
    foreground: root.windowOpened ? Commons.Color.popups.text : root.barForeground
    windowMode: editorWindow.visible
    onCloseRequested: root.close()
    onWindowRequested: root.openWindow()
    onSwitchRequested: function(direction) { root.switchPanel(direction) }
    onFocusRequested: root.revealFocus()
  }

  KeyboardPanel {
    id: popup
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: editor
    contentWidth: popup.fittedContentWidth(Style.space(470))
    contentHeight: popup.fittedContentHeight(editor.implicitHeight)

    Flickable {
      id: popupScroll
      anchors.fill: parent
      contentWidth: width
      contentHeight: editor.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      onHeightChanged: root.revealFocus()
      onContentHeightChanged: root.revealFocus()
    }
  }

  FloatingWindow {
    id: editorWindow
    title: "Controller Control"
    visible: false
    color: Commons.Color.popups.background
    implicitWidth: Style.space(600)
    implicitHeight: Style.space(680)
    minimumSize: Qt.size(320, 240)
    onVisibleChanged: if (!visible && !root.opened) root.cancelCaptureIfActive()

    Flickable {
      id: windowScroll
      anchors.fill: parent
      anchors.margins: Style.space(18)
      contentWidth: width
      contentHeight: editor.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      onHeightChanged: root.revealFocus()
      onContentHeightChanged: root.revealFocus()
    }
  }
}
