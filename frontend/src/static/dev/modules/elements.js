export function getDevKioskElements(documentRef = document) {
  return {
    kioskRoot: documentRef.getElementById('kioskRoot'),
    chatBox: documentRef.getElementById('chatBox'),
    voiceIndicator: documentRef.getElementById('voiceIndicator'),
    avatarEl: documentRef.getElementById('kioskAvatar'),
    debugStatsEl: documentRef.getElementById('debugStats'),
    debugRuntimeEl: documentRef.getElementById('debugRuntime'),
    faceIndicator: documentRef.getElementById('faceIndicator'),
    faceIndicatorText: documentRef.getElementById('faceIndicatorText'),
    faceCamera: documentRef.getElementById('faceCamera')
  };
}
