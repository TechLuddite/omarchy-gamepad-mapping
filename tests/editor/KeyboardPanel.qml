import QtQuick
// Offscreen-only replacement for the layer-shell surface; never installed.
// It claims and releases its bar like the real panel, so moving the popup
// between bars goes through the same handoff.
Item {
  id: popup
  property var anchorItem: null
  property var owner: null
  property var bar: null
  property bool open: false
  property var focusTarget: null
  property real contentWidth: 470
  property real contentHeight: 600
  width: contentWidth
  height: contentHeight
  visible: open
  function fittedContentWidth(value) { return value }
  function fittedContentHeight(value) { return Math.min(600, value) }
  onOpenChanged: {
    if (open && focusTarget) focusTarget.forceActiveFocus()
    if (!bar) return
    var key = owner || popup
    if (open) bar.requestPopout(key)
    else if (bar.activePopout === key) bar.releasePopout(key)
  }
}
