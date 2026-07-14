/* =================================================================
   CHAT TAB — Thin compatibility shell (Phase 3c)
   All functional code extracted to chat/*.js modules.
   ================================================================= */
const CHAT = window.Nous.Chat.state;

/* chat-core.js: state, loadChat, input handlers, panel toggles, debug */
/* chat-settings.js: loadChatConfig, renderSkillsList, renderSettingsPanel */
/* chat-send.js: appendChatMessage, chatSend, typing indicator, findChatLogContainer, scrollToBottom */
/* chat-history.js: restoreChatHistory, resetToWelcome, clearChatHistory, getChatSessionId, rollbackChat, editChatMessage, exportChatHistory */
/* chat-markdown.js: safeMarkdown, renderCodeBlock */
/* chat-memory-panel.js: updateMemoryPanel, reflection, memory editing */
/* chat-tools.js: appendToolEvent, handleFileToolCall, execCodeBlock, image spinner, fetchMcpTools, renderMcpTools, toggleTool */
/* chat-equipment.js: loadEquipment, updateEquipmentPanel */
/* chat-commands.js: SLASH_COMMANDS, showHelpCommand, command popup, handleSlashCommand */
/* chat-attachments.js: uploadAttachment, renderAttachmentBadge, openMediaViewer, closeMediaViewer */
/* chat-tts.js: loadVoiceModels, testVoicePlayback, playTts, autoPlayTts */
/* chat-voice.js: toggleVoiceInput */
/* chat-portrait.js: loadPortrait, setPortraitImage, onPortraitClick */

// ESC key closes settings panel on mobile
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape" && CHAT.sidebarOpen) {
    var isMobile = window.innerWidth <= 768;
    if (isMobile) {
      toggleSettingsPanel();
    }
  }
});

// Reload chat config when persona changes
let __chatPersonaTries = 0;
const __CHAT_PERSONA_MAX_TRIES = 20;
window.__chatPersonaWatcher = setInterval(() => {
  const sel = document.getElementById("persona-select");
  if (!sel) {
    __chatPersonaTries++;
    if (__chatPersonaTries >= __CHAT_PERSONA_MAX_TRIES) {
      console.warn("[chat] #persona-select not found after 20 tries, giving up");
      clearInterval(window.__chatPersonaWatcher);
    }
    return;
  }
  if (!sel._chatBound) {
    sel._chatBound = true;
    sel.addEventListener("change", () => {
      if (S.tab === "chat") {
        loadChatConfig();
        loadChatCommitments();
      }
    });
    clearInterval(window.__chatPersonaWatcher);
  }
}, 500);


