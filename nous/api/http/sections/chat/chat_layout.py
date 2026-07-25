"""Chat tab layout — container, message area, and input area HTML."""



def render_chat_layout_prefix() -> str:
    """Return the opening HTML (CSS link, section, header, layout container, backdrop)."""
    return """
        <!-- ========== CHAT TAB ========== -->
        <section id="tab-chat" class="tab-panel" role="tabpanel">
            <div style="position:relative; margin-bottom:16px; display:flex; align-items:center; justify-content:space-between; padding-bottom:12px; border-bottom:1px solid var(--glass-border);">
                <h2 style="font-size:1.25rem; font-weight:700; color:var(--text-primary); display:flex; align-items:center; gap:10px;"><span style="font-size:1.4rem;"><i data-lucide="message-circle"></i></span> Chat</h2>
                <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
                    <button class="mem-panel-toggle" id="memory-panel-toggle-btn" onclick="N.Chat.core.toggleMemory()" title="記憶パネルを開閉" aria-label="記憶パネルの表示切替"><i data-lucide="brain"></i></button>
                    <button class="chat-sidebar-toggle" onclick="N.Chat.core.toggleSettings()" id="chat-sidebar-toggle-btn" title="設定パネルを開閉" aria-label="設定パネルの表示切替"><i data-lucide="settings"></i></button>
                </div>
            </div>
            <div id="chat-layout" class="glass" style="padding:0; overflow:hidden;">
                <!-- Mobile backdrop for settings panel -->
                <div id="settings-backdrop" onclick="N.Chat.core.toggleSettings()"></div>
                """


def render_chat_main() -> str:
    """Return the chat main area (messages, status, attachments, input area)."""
    return """

                <!-- Chat area -->
                <div id="chat-main">
                    <div id="chat-messages">
                        <div class="chat-welcome" id="chat-welcome">
                            <div class="chat-welcome-icon"><i data-lucide="message-circle"></i></div>
                            <p>チャットを開始するには下のテキストボックスにメッセージを入力してください。</p>
                            <p class="chat-welcome-hint">APIキーとプロバイダーを設定してください。<br><a href="#" onclick="N.Chat.core.toggleSettings();return false;" class="chat-welcome-link"><i data-lucide="settings"></i> 設定パネルを開く</a></p>
                            <div class="chat-welcome-commands">
                                <span class="chat-welcome-cmd">/memory</span>
                                <span class="chat-welcome-cmd">/goal</span>
                                <span class="chat-welcome-cmd">/help</span>
                                <span class="chat-welcome-cmd">/search</span>
                                <span class="chat-welcome-cmd">/image</span>
                                <span class="chat-welcome-cmd">/invoke_skill</span>
                            </div>
                        </div>
                    </div>
                    <div id="chat-status"></div>
                    <div id="chat-attachments"></div>
                    <div id="chat-input-area">
                        <textarea id="chat-input" placeholder="メッセージを入力... (Shift+Enter で送信、Enter で改行)" rows="1" aria-label="チャットメッセージ入力"></textarea>
                        <div style="display:flex;align-items:center;gap:6px;">
                            <button id="chat-cancel-btn" class="chat-stop-btn" onclick="N.Chat.cancel()" style="display:none" aria-label="応答を停止"><i data-lucide="stop-circle"></i> 中止</button>
                            <button id="chat-attach-btn" class="chat-action-btn" onclick="N.Chat.attachments.trigger()" title="ファイル添付" aria-label="ファイルを添付"><i data-lucide="paperclip"></i></button>
                            <button id="chat-voice-btn" class="chat-action-btn" onclick="N.Chat.voice.toggle()" title="音声入力" aria-label="音声入力の切替"><i data-lucide="mic"></i></button>
                            <button id="chat-export-btn" class="chat-action-btn" onclick="N.Chat.history.export()" title="会話をエクスポート" aria-label="会話履歴をエクスポート"><i data-lucide="download"></i></button>
                            <button id="chat-send-btn" onclick="N.Chat.send()" aria-label="メッセージを送信">送信</button>
                        </div>
                    </div>
                </div>"""


def render_chat_layout_suffix() -> str:
    """Return the closing HTML (layout close, highlight.js, media viewer, section close)."""
    return """
            </div>
            <!-- highlight.js for syntax highlighting in chat bubbles -->
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
            <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js" crossorigin="anonymous"></script>
            <!-- Media viewer overlay -->
            <div id="media-viewer-overlay" onclick="N.Chat.attachments.closeViewer()">
                <div id="media-viewer-inner" onclick="event.stopPropagation()"></div>
            </div>
        </section>"""
